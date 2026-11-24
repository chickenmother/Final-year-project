"""CLOUD X (the cloud tier). Runs the full game, renders high quality, streams to Y."""
import asyncio, collections, csv, io, json, os, struct, time
from websockets.asyncio.server import serve
from common import config as C
from common import pipeline as P
from common.leaderboard import Leaderboard, LeaderboardError
from common.net import lan_ip, quiet_handshake_errors
from common.placement import (
    PlacementError,
    TASKS,
    edge_pipeline,
    validate as validate_placement,
)
from common.pipeline import Chain, ChannelStats
from common.win import hires_timer
from common.xstats import FrameStats
hires_timer()
quiet_handshake_errors()
from game.simulation import Game
try:
    from common.video import H264Encoder
except ImportError:                      # PyAV not installed: JPEG only
    H264Encoder = None

game = Game()
resync = False
game_over_sent = False
x_encoder = None
log_f = log_w = None
n_logged = 0
stats = FrameStats(window_s=2.0)         # rolling encoder stats (WS2.3)
placement_owner = list(TASKS)           # tasks Cloud X currently runs (WS3.1)
leaderboard = None                      # L: SQLite store on X (WS3.4)
chain = None                            # WS3.5 custom stage chain
chain_stats = ChannelStats()            # crossings/stalls/stage timings


async def apply_video(m):
    """Rebuild the encoder for a runtime ``video`` command (WS2.3).

    The codec is opened off the event loop because libx264 init can take tens
    of milliseconds; the caller drops the queued frames and forces an IDR so
    End Z resynchronises (a size change also needs that keyframe).
    """
    global x_encoder
    if H264Encoder is None:
        return {"t": "error", "command": "video",
                "message": "PyAV is unavailable; X is streaming JPEG"}
    try:
        size = tuple(int(v) for v in (m.get("size") or C.X_SIZE))
        gop = int(m.get("gop") or C.X_GOP)
        bitrate = int(m.get("bitrate") or C.X_BITRATE)
        intra = bool(m.get("intra_refresh", C.X_INTRA_REFRESH))
        encoder = str(m.get("encoder") or C.X_ENCODER)
    except (TypeError, ValueError) as exc:
        return {"t": "error", "command": "video", "message": f"bad settings: {exc}"}

    def build():
        return H264Encoder(size, C.X_FPS, bitrate, gop, encoder=encoder,
                           intra_refresh=intra)

    try:
        new = await asyncio.to_thread(build)
    except Exception as exc:
        print(f"[{time.strftime('%X')}] video: encoder rebuild failed ({exc!r})")
        return {"t": "error", "command": "video",
                "message": f"encoder rebuild failed: {exc}"}
    old, x_encoder = x_encoder, new
    if old is not None:
        try:
            old.close()
        except Exception:
            pass
    print(f"[{time.strftime('%X')}] X video: {new.name} "
          f"{size[0]}x{size[1]} @ {C.X_FPS} fps, {bitrate} bps, GOP {gop}, "
          f"intra-refresh={'on' if intra else 'off'}")
    return {"t": "video_ok", "encoder": new.name, "gop": gop,
            "size": [size[0], size[1]], "bitrate": bitrate,
            "intra_refresh": intra}



def log_frame(tick, seq, codec, key, encode_ms, nbytes):
    global n_logged
    log_w.writerow([round(time.time(), 3), tick, seq, codec, int(bool(key)),
                    round(encode_ms, 1), nbytes])
    n_logged += 1
    if n_logged % 30 == 0:
        log_f.flush()


async def handler(ws):
    global resync, game_over_sent, game, x_encoder, placement_owner, chain, chain_stats
    # Do NOT reset the game on connect: ask Y for its snapshot instead, so the
    # two tiers converge on whichever side kept the newer state. This also
    # survives a Y or X restart without a visible jump.
    resync, need_at = True, time.monotonic()
    z_h264, force_key, streaming = False, True, True
    paused, playing = False, False
    stats_on = False
    remote_ab = False
    edge_mode = False
    print(f"Y connected from {ws.remote_address}")
    lock = asyncio.Lock()

    async def send(data):                 # one writer at a time (frames + control share the socket)
        async with lock:
            await ws.send(data)

    await send(json.dumps({"t": "need_snap"}))

    q, ev = collections.deque(), asyncio.Event()
    out = {"queue": collections.deque(), "jpeg": None, "ev": asyncio.Event(), "need_key": False}

    async def reader():                   # keeps reading even while we are busy rendering
        try:
            async for msg in ws:
                q.append(msg)
                ev.set()
        finally:
            ev.set()

    async def sender():
        """H.264 packets go out in order; JPEG keeps newest-frame-wins."""
        while True:
            await out["ev"].wait()
            out["ev"].clear()
            while out["queue"]:
                await send(out["queue"].popleft())
            if out["jpeg"] is not None:
                data, out["jpeg"] = out["jpeg"], None
                await send(data)

    rd = asyncio.create_task(reader())
    sd = asyncio.create_task(sender())

    async def stats_pump():
        """Push a 1 Hz encoder summary while Y has the subscription on."""
        while True:
            await asyncio.sleep(1.0)
            if stats_on and stats.mature():
                payload = {"t": "x_stats", **stats.snapshot()}
                if chain is not None:
                    payload["chain"] = chain_stats.snapshot()   # WS3.5
                await send(json.dumps(payload))

    async def run_chain(stage, keys, seq, snapshot):
        """WS3.5: run X's slice of the custom chain; forwards at a crossing."""
        run, forward = chain.local_run(stage, "X")
        if not run:
            return None                  # not ours (Y forwarded wrongly)
        if snapshot is not None:
            game.restore(snapshot, effects=False)
        ctx = {"surface": None, "render_ms": None, "sim_ms": None,
               "hit_ms": None, "stream_here": "E" in run}
        for name in run:
            t_stage = time.perf_counter()
            if name == "A":
                t0 = time.perf_counter()
                game.step_a(keys)
                ctx["sim_ms"] = (time.perf_counter() - t0) * 1000
            elif name == "B":
                t0 = time.perf_counter()
                game.step_b()
                ms = (time.perf_counter() - t0) * 1000
                ctx["sim_ms"] = (ctx["sim_ms"] or 0.0) + ms
            elif name == "C":
                t0 = time.perf_counter()
                game.step_c()
                ctx["hit_ms"] = (time.perf_counter() - t0) * 1000
            elif name == "D":
                t0 = time.perf_counter()
                ctx["surface"] = game.render_surface(C.X_SIZE, True)
                ctx["render_ms"] = (time.perf_counter() - t0) * 1000
            chain_stats.stage(name, (time.perf_counter() - t_stage) * 1000)
        if forward is None:
            return ctx                   # E ran here: the caller streams it
        if forward == "E":
            # D here, E on Y: ship the rendered pixels (JPEG unless RAW).
            fmt = P.pixel_format(raw=False, quality=C.X_QUALITY)
            data = game.render(C.X_SIZE, C.X_QUALITY)
            payload = P.pixels_message(game.tick, seq, fmt, C.X_SIZE,
                                       game.snapshot(), data)
            chain_stats.crossing(P.PIXELS, len(payload))
            await send(payload)
            return ctx
        payload = P.stage_message(forward, game.tick, seq, keys,
                                  game.snapshot())
        chain_stats.crossing(P.STATE, len(payload))
        await send(payload)
        return ctx

    stp = asyncio.create_task(stats_pump())

    async def emit_frame(seq, ctx=None):
        """Render + encode one tick for End Z (WS3.2 path and WS3.5 stages D/E).

        ``ctx["surface"]`` lets stage D hand its rendered frame straight to E,
        so the custom chain never renders a tick twice.
        """
        global x_encoder
        nonlocal force_key
        ctx = ctx or {}
        t0 = time.perf_counter()
        is_key = True
        render_ms = ctx.get("render_ms")
        if x_encoder is not None and z_h264:
            try:
                frame = ctx.get("surface")
                if frame is None:
                    t_render = time.perf_counter()
                    frame = game.render_surface(C.X_SIZE, True)
                    render_ms = (time.perf_counter() - t_render) * 1000
                if force_key or out["need_key"]:
                    x_encoder.force_keyframe()
                    force_key = out["need_key"] = False
                packets = x_encoder.encode_surface(frame)
                nbytes, codec, is_key = 0, "h264", False
                for payload, key in packets:
                    nbytes += len(payload)
                    is_key = is_key or key
                    out["queue"].append(
                        b"x" + bytes([1 if key else 0])
                        + struct.pack("!II", game.tick, seq) + payload)
                if out["queue"]:
                    out["ev"].set()
                if len(out["queue"]) > 90:      # ~1 s behind: resync at next IDR
                    out["queue"].clear()
                    out["need_key"] = True
            except Exception as exc:            # encoder failed: keep streaming
                print(f"H.264 encode failed ({exc!r}); falling back to JPEG")
                x_encoder = None
                jpg = game.render(C.X_SIZE, C.X_QUALITY)
                out["jpeg"] = b"X" + struct.pack("!II", game.tick, seq) + jpg
                out["ev"].set()
                nbytes, codec, is_key = len(jpg), "jpeg", True
        else:
            jpg = game.render(C.X_SIZE, C.X_QUALITY)
            out["jpeg"] = b"X" + struct.pack("!II", game.tick, seq) + jpg
            out["ev"].set()
            nbytes, codec, is_key = len(jpg), "jpeg", True
        encode_ms = (time.perf_counter() - t0) * 1000
        log_frame(game.tick, seq, codec, is_key, encode_ms, nbytes)
        stats.add(encode_ms, nbytes, is_key, sim_ms=ctx.get("sim_ms"),
                  hit_ms=ctx.get("hit_ms"), render_ms=render_ms)
        return nbytes

    async def emit_pixels(seq, fmt, size, data, snapshot=None):
        """WS3.5: D ran on Y, E runs here — encode the received pixels."""
        global x_encoder
        nonlocal force_key
        if snapshot is not None:
            game.restore(snapshot, effects=False)   # our tick follows theirs
        chain_stats.encoded()
        if x_encoder is not None and z_h264:
            try:
                from PIL import Image
                if fmt == "raw":
                    img = Image.frombytes("RGBA", (int(size[0]), int(size[1])),
                                          data).convert("RGB")
                else:
                    img = Image.open(io.BytesIO(data)).convert("RGB")
                if force_key or out["need_key"]:
                    x_encoder.force_keyframe()
                    force_key = out["need_key"] = False
                t_enc = time.perf_counter()
                packets = x_encoder.encode(img)
                encode_ms = (time.perf_counter() - t_enc) * 1000
                nbytes, is_key = 0, False
                for payload, key in packets:
                    nbytes += len(payload)
                    is_key = is_key or key
                    out["queue"].append(
                        b"x" + bytes([1 if key else 0])
                        + struct.pack("!II", game.tick, seq) + payload)
                if out["queue"]:
                    out["ev"].set()
                log_frame(game.tick, seq, "h264", is_key, encode_ms, nbytes)
                stats.add(encode_ms, nbytes, is_key)
            except Exception as exc:
                print(f"H.264 encode of remote pixels failed ({exc!r})")
                x_encoder = None
                chain_stats.stall(game.tick)
        elif fmt != "raw":
            # No encoder on this tier: re-frame the JPEG, End Z scales it.
            out["jpeg"] = b"X" + struct.pack("!II", game.tick, seq) + data
            out["ev"].set()
            log_frame(game.tick, seq, "jpeg", True, 0.0, len(data))
            stats.add(0.0, len(data), True)
        else:
            chain_stats.stall(game.tick)     # no H.264, no way to ship raw
        if chain is not None and chain.stream_tier == "X":
            await send(P.final_message(game.tick, seq, game.snapshot()))
    try:
        while True:
            if not q:
                if rd.done():
                    break
                ev.clear()
                await ev.wait()
                continue
            raw = q.popleft()
            if isinstance(raw, (bytes, bytearray)):
                parsed = P.parse_pixels(raw)
                if parsed is not None and chain is not None:
                    # WS3.5: D on Y, E here — encode the pixels Y rendered.
                    tick, seq, fmt, size, snapshot, data = parsed
                    chain_stats.crossing(P.PIXELS, len(raw))
                    await emit_pixels(seq, fmt, size, data, snapshot)
                continue
            m = json.loads(raw)
            t = m["t"]
            if t == "stage" and chain is not None:
                # WS3.5: Y started a tick whose stages live here.
                if not playing:
                    continue
                try:
                    stage, tick, seq, keys, snapshot = P.parse_stage(m)
                except P.PipelineError as exc:
                    print(f"bad stage message: {exc}")
                    continue
                if paused:
                    continue
                ctx = run_chain(stage, keys, seq, snapshot)
                if ctx is None:
                    continue
                if game.game_over:
                    if not game_over_sent:
                        game_over_sent, playing = True, False
                        await send(json.dumps({"t": "game_over",
                                               "score": game.score,
                                               "deaths": game.deaths}))
                elif ctx.get("surface") is not None or ctx.get("stream_here"):
                    await emit_frame(seq, ctx)
                if chain.stream_tier == "X":
                    await send(P.final_message(game.tick, seq, game.snapshot()))
                continue
            if t == "pong":
                await send(json.dumps({"t": "pong", "ts": m["ts"]}))
            elif t == "snap":
                config = m.get("config")
                if config:
                    game = Game(m["s"].get("workload", "light"),
                                seed=game.seed, config=config)
                game.restore(m["s"])
                resync, playing = False, True
                print(f"resynced at tick {game.tick}")
            elif t == "caps":
                # Y reports whether every connected Z can decode H.264.
                new = bool(m.get("h264"))
                if new != z_h264:
                    print(f"[{time.strftime('%X')}] X stream codec: "
                          f"{'H.264' if new else 'JPEG'}")
                    z_h264, force_key = new, new
            elif t == "need_idr":
                force_key = True
            elif t == "stream":
                new = bool(m.get("on", True))
                if new != streaming:
                    streaming = new
                    if streaming:
                        force_key = True        # resume with an IDR
                    else:
                        out["queue"].clear()
                        out["jpeg"] = None
                    print(f"[{time.strftime('%X')}] X video: "
                          f"{'streaming' if streaming else 'paused (EDGE Y)'}")
            elif t == "pause":
                paused = True
                print("game paused")
            elif t == "resume":
                paused = False
                print("game resumed")
            elif t == "video":
                # WS2.3: swap GOP/size/bitrate/intra-refresh without a restart.
                reply = await apply_video(m)
                if reply.get("t") == "video_ok":
                    force_key = True            # Z needs an IDR after the swap
                    out["queue"].clear()
                    out["jpeg"] = None
                    stats.reset()
                await send(json.dumps(reply))
            elif t == "stats":
                stats_on = bool(m.get("on", True))
                print(f"[{time.strftime('%X')}] X stats: "
                      f"{'on' if stats_on else 'off'}")
            elif t == "stop":
                # Stop stepping/streaming but keep the process and socket.
                playing = paused = False
                streaming = False
                out["queue"].clear()
                out["jpeg"] = None
                stats.reset()
                await send(json.dumps({"t": "stopped"}))
                print(f"[{time.strftime('%X')}] X stopped by request")
            elif t == "placement":
                # WS3.1/WS3.2: Y's router tells X which tasks it owns.
                # All Cloud runs A-E on X; Offload A/B moves A+B to Y, so X
                # restores the uploaded state and runs only C-E.
                try:
                    table = validate_placement(m.get("tasks") or {})
                except PlacementError as exc:
                    await send(json.dumps({"t": "error", "command": "placement",
                                           "message": str(exc)}))
                    continue
                if m.get("custom"):
                    # WS3.5: any A-E assignment; the chain decides every hop.
                    chain = Chain(table)
                    chain_stats = ChannelStats()
                    placement_owner = [task for task in TASKS
                                       if table.get(task) == "X"]
                    remote_ab = edge_mode = False
                    playing = True
                    print(f"[{time.strftime('%X')}] X chain: "
                          f"{chain.describe()}")
                    await send(json.dumps({
                        "t": "placement_ok", "custom": True,
                        "tasks": {task: "X" for task in placement_owner}}))
                    continue
                chain = None
                owned = [task for task in TASKS if table.get(task) == "X"]
                missing = [task for task in ("C", "D", "E") if task not in owned]
                ab_on_y = table.get("A") == "Y" and table.get("B") == "Y"
                ab_on_x = "A" in owned and "B" in owned
                edge_only = edge_pipeline(table)
                if not edge_only and (missing or not (ab_on_y or ab_on_x)):
                    await send(json.dumps({
                        "t": "error", "command": "placement",
                        "message": ("X needs C, D, E and either all of A/B or "
                                    "neither, or the whole A-E pipeline on Y "
                                    f"(All Edge): {', '.join(missing) or 'A/B split'}"
                                    )}))
                    continue
                placement_owner = owned
                remote_ab = ab_on_y and not edge_only
                edge_mode = edge_only
                if edge_only:
                    # WS3.3: X keeps only L; stop stepping/streaming.
                    playing = paused = streaming = False
                    out["queue"].clear()
                    out["jpeg"] = None
                    stats.reset()
                print(f"[{time.strftime('%X')}] X placement: tasks {owned}" +
                      (" (All Edge: X idle, L only)" if edge_only
                       else " (A/B from Y state)" if remote_ab else ""))
                await send(json.dumps({"t": "placement_ok",
                                       "tasks": {task: "X" for task in owned}}))
            elif t == "task":
                # WS3.4: L is pinned to X, so Y routes every score here.
                ident = m.get("id")
                if ident != "L":
                    await send(json.dumps({"t": "task_result", "id": ident,
                                           "ok": False,
                                           "error": f"task {ident!r} is not on X"}))
                    continue
                op = str(m.get("op") or "")
                try:
                    if op == "submit":
                        result = leaderboard.submit(m.get("entry") or {})
                    elif op == "top":
                        result = {"rows": leaderboard.top(m.get("top", 10)),
                                  "count": leaderboard.count()}
                    else:
                        raise LeaderboardError(f"unknown L op {op!r}")
                except LeaderboardError as exc:
                    await send(json.dumps({"t": "task_result", "id": "L",
                                           "ok": False, "error": str(exc)}))
                    continue
                await send(json.dumps({"t": "task_result", "id": "L", "ok": True,
                                       **result}))
                print(f"[{time.strftime('%X')}] L {op}: {leaderboard.count()} "
                      f"row(s)")
            elif t == "start":
                try:
                    game = Game(m.get("workload", "light"),
                                seed=int(m.get("seed", 12345)),
                                config=m.get("config"))
                except Exception as exc:
                    print(f"invalid game config ({exc}); using defaults")
                    game = Game(m.get("workload", "light"),
                                seed=int(m.get("seed", 12345)))
                resync, game_over_sent = False, False
                # WS3.3: an All Edge placement leaves X with L only, so a
                # start must not wake the renderer again.  WS3.5: a custom
                # chain keeps X listening for the stages Y routes to it.
                paused, playing = False, (not edge_mode or chain is not None)
                if chain is not None:
                    chain_stats = ChannelStats()
                force_key = True
                out["queue"].clear()
                out["jpeg"] = None
                print(f"[{time.strftime('%X')}] game start: "
                      f"workload={game.workload.name} seed={game.seed} "
                      f"hp={game.player.max_hp} bots={game.workload.bots} "
                      f"obstacles={game.workload.obstacles}")
            elif t in ("in", "state"):
                if not playing:
                    continue
                if t == "in":
                    if paused or m["tick"] != game.tick + 1:
                        continue
                    # All Cloud: X runs A+B here, C below (same split as Y).
                    t_sim = time.perf_counter()
                    game.step_ab(m["keys"])
                    sim_ms = (time.perf_counter() - t_sim) * 1000
                else:
                    # Offload A/B: Y already ran A+B; restore its state and
                    # apply C here. effects=False keeps X's own particles.
                    game.restore(m["s"], effects=False)
                    sim_ms = None
                if True:
                    t_hit = time.perf_counter()
                    game.step_c()
                    hit_ms = (time.perf_counter() - t_hit) * 1000
                    if game.game_over and not game_over_sent:
                        game_over_sent, playing = True, False
                        await send(json.dumps({"t": "game_over",
                                               "score": game.score,
                                               "deaths": game.deaths}))
                    # render + encode costs ~6.5 ms at 720p/60 on the reference
                    # machine, so render every stream tick. Skipping a tick used
                    # to force an IDR, which caused 100-200 KB keyframe bursts
                    # and the latency/jitter spikes.
                    if not game.game_over and game.tick % C.X_STREAM_EVERY == 0 and streaming:
                        await emit_frame(m["seq"], {"sim_ms": sim_ms,
                                                    "hit_ms": hit_ms})
                    if (t == "in" and m["tick"] > game.tick + 1
                            and (not resync
                                 or time.monotonic() - need_at > 2.0)):
                        resync, need_at = True, time.monotonic()
                        await send(json.dumps({"t": "need_snap"}))
    finally:
        rd.cancel()
        sd.cancel()
        stp.cancel()
        await asyncio.gather(rd, sd, stp, return_exceptions=True)
        print("Y disconnected")


async def main():
    global log_f, log_w, x_encoder, leaderboard
    os.makedirs("logs", exist_ok=True)
    leaderboard = Leaderboard(os.path.join("logs", "leaderboard.db"))
    print(f"L store: {os.path.abspath(leaderboard.path)} "
          f"({leaderboard.count()} row(s))")
    log_f = open(os.path.join("logs", "log_x.csv"), "w", newline="")
    log_w = csv.writer(log_f)
    log_w.writerow(["unix_time", "tick", "seq", "codec", "key",
                    "encode_ms", "frame_bytes"])

    if C.X_CODEC == "h264" and H264Encoder is not None:
        try:
            x_encoder = H264Encoder(C.X_SIZE, C.X_FPS, C.X_BITRATE, C.X_GOP,
                                    encoder=C.X_ENCODER,
                                    intra_refresh=C.X_INTRA_REFRESH)
            print(f"X video encoder: H.264 via {x_encoder.name} "
                  f"({C.X_SIZE[0]}x{C.X_SIZE[1]} @ {C.X_FPS} fps, "
                  f"{C.X_BITRATE} bps, GOP {C.X_GOP}, "
                  f"intra-refresh={'on' if C.X_INTRA_REFRESH else 'off'})")
        except Exception as exc:
            print(f"X video encoder: H.264 unavailable ({exc}); using JPEG")
            x_encoder = None
    else:
        print("X video encoder: JPEG (FYP_X_CODEC=jpeg or PyAV missing)")
    try:
        async with serve(handler, C.X_HOST, C.X_PORT, max_size=4 << 20, compression=None,
                         ping_interval=C.PING_INTERVAL, ping_timeout=C.PING_TIMEOUT):
            print(f"X ready: ws://{lan_ip()}:{C.X_PORT}  (listening on {C.X_HOST}:{C.X_PORT})")
            print(f"X tasks: {', '.join(placement_owner)} "
                  f"(placement is set by Y's router)")
            await asyncio.Future()
    finally:
        if x_encoder is not None:
            x_encoder.close()
        log_f.close()


try:
    asyncio.run(main())
except KeyboardInterrupt:
    pass
