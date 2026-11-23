"""CLOUD X (the cloud tier). Runs the full game, renders high quality, streams to Y."""
import asyncio, collections, csv, json, os, struct, time
from websockets.asyncio.server import serve
from common import config as C
from common.net import lan_ip, quiet_handshake_errors
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
    global resync, game_over_sent, game, x_encoder
    # Do NOT reset the game on connect: ask Y for its snapshot instead, so the
    # two tiers converge on whichever side kept the newer state. This also
    # survives a Y or X restart without a visible jump.
    resync, need_at = True, time.monotonic()
    z_h264, force_key, streaming = False, True, True
    paused, playing = False, False
    stats_on = False
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
                await send(json.dumps({"t": "x_stats", **stats.snapshot()}))

    stp = asyncio.create_task(stats_pump())
    try:
        while True:
            if not q:
                if rd.done():
                    break
                ev.clear()
                await ev.wait()
                continue
            m = json.loads(q.popleft())
            t = m["t"]
            if t == "ping":
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
                paused, playing = False, True
                force_key = True
                out["queue"].clear()
                out["jpeg"] = None
                print(f"[{time.strftime('%X')}] game start: "
                      f"workload={game.workload.name} seed={game.seed} "
                      f"hp={game.player.max_hp} bots={game.workload.bots} "
                      f"obstacles={game.workload.obstacles}")
            elif t == "in":
                if not playing:
                    continue
                if not paused and m["tick"] == game.tick + 1:
                    game.step(m["keys"])
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
                        seq = m["seq"]
                        t0 = time.perf_counter()
                        is_key = True
                        if x_encoder is not None and z_h264:
                            try:
                                frame = game.render_surface(C.X_SIZE, True)
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
                        stats.add(encode_ms, nbytes, is_key)
                elif m["tick"] > game.tick + 1 and (not resync or time.monotonic() - need_at > 2.0):
                    resync, need_at = True, time.monotonic()
                    await send(json.dumps({"t": "need_snap"}))
    finally:
        rd.cancel()
        sd.cancel()
        stp.cancel()
        await asyncio.gather(rd, sd, stp, return_exceptions=True)
        print("Y disconnected")


async def main():
    global log_f, log_w, x_encoder
    os.makedirs("logs", exist_ok=True)
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
            await asyncio.Future()
    finally:
        if x_encoder is not None:
            x_encoder.close()
        log_f.close()


try:
    asyncio.run(main())
except KeyboardInterrupt:
    pass
