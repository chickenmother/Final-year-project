"""EDGE Y (laptop A): sequencer + fallback renderer + latency monitor + mode switch + dashboard backend."""
import asyncio, collections, csv, io, json, os, struct, sys, time
from websockets.exceptions import ConnectionClosed
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from common import config as C
from common import pipeline as P
from common import report as report_mod
from common.net import lan_ip, quiet_handshake_errors
from common.pipeline import Chain, ChannelStats
from common.placement import (
    PlacementError,
    TaskStats,
    describe as describe_placement,
    edge_pipeline,
    merge_metrics,
    pattern_table,
    remote_ab as placement_remote_ab,
    render_tier,
    validate as validate_placement,
)
from common.testplan import MODE_OVERRIDE, PlanError, TestPlan, video_payload
from common.win import hires_timer
hires_timer()
quiet_handshake_errors()
from game.simulation import Game
try:
    from common.video import H264Encoder
except ImportError:                      # PyAV not installed: JPEG fallback
    H264Encoder = None

TICK = 1 / C.TICK_RATE
game = Game()
state = {"mode": "X", "rtt": 0.0, "rtt_zy": 0.0, "lag": 0, "delay_ms": 0,
         "e2e": 0.0, "tick": 0, "linked": False, "playing": False,
         "paused": False, "mode_override": None, "test": None,
         "z_stats": {}, "x_stats": {}, "x_video": {}, "x_fps": 0.0, "y_fps": 0.0,
         "placement": {}, "placement_pattern": "legacy", "placement_applied": False,
         "x_placement": {}, "task_stats": {}, "offload": {}, "remote_ab": False,
         "edge_only": False, "leaderboard": [], "reports": [],
         "chain": {}, "chain_crossings": 0, "chain_desc": "",
         "channels": {}, "x_channels": {}, "stalls": 0,
         "x_build": "", "x_chain": None, "chain_warning": ""}
inp = {"keys": "", "seq": 0, "latch": False}
zs = {}                # Z connection -> frame queue + capability slot
last_fwd, bad, good_since = 0, 0, None
paused = False
up = down = None
log_f = log_w = None
y_encoder = None       # H.264 encoder for the EDGE Y fallback stream
last_caps = None       # last H.264 capability advertised to X
last_stream = None     # last "X video on/off" advertised to X
y_force_key = False    # force an IDR on the next EDGE Y frame
x_frame_times = collections.deque()     # X frames received (for x_fps)
y_frame_times = collections.deque()     # frames broadcast by Y (for y_fps)
test_runner = None
task_stats = TaskStats()               # per-task timings measured on Y (WS3.1)
offload = {"n": 0, "bytes": 0, "kb_s": 0.0, "total": 0}   # WS3.2 state upload
offload_window = collections.deque()   # (t, bytes) over the last second
edge_over_sent = False                 # WS3.3: Y owns the game-over event
lb_pending = {}                        # ws -> timeout task for a pending L request
Y_BUILD = "ws3.5"                      # advertised by {"t":"version"}
# WS3.4.1: a measurement must not end early, so tests overlay a safe player on
# Z's own config (FYP_TEST_SAFE=0 restores the raw match tuning).  Bot *bullets*
# are the damage source during a normal match, so they are zeroed as well.
SAFE_TESTS = os.environ.get("FYP_TEST_SAFE", "1") != "0"
SAFE_TEST_CONFIG = {
    "player": {"max_hp": 1000, "obstacle_damage": 0, "bot_damage": 0},
    "bot": {"bullet_damage": 0},
}
# WS3.5: custom placements run as a stage chain.  Pixels cross D->E as JPEG
# unless FYP_PIXELS_RAW=1 asks for RGBA bytes (2.8 MB per 720p frame).
chain = None                             # common.pipeline.Chain or None
chain_stats = ChannelStats()             # crossings/stalls/stage timings
PIXELS_RAW = os.environ.get("FYP_PIXELS_RAW", "0") == "1"


def count_offload(nbytes):
    """Track the state upload rate Y pays for Offload A/B (WS3.2)."""
    now = time.monotonic()
    offload_window.append((now, int(nbytes)))
    while offload_window and offload_window[0][0] < now - 1.0:
        offload_window.popleft()
    sent = sum(size for _, size in offload_window)
    offload["n"] = len(offload_window)
    offload["bytes"] = sent
    offload["total"] += int(nbytes)
    offload["kb_s"] = round(sent / 1024, 1)
    state["offload"] = dict(offload)
REPORT_DIR = os.path.join("logs", "reports")



class DelayLine:                       # simulated one-way network delay, order preserving
    """fn is the current sink (xws.send / on_x_msg). While it is None the line
    is disconnected and messages are dropped instead of piling up."""
    def __init__(self):
        self.q, self.fn, self.delay = asyncio.Queue(), None, 0.0
    def put(self, d):
        """Queue a message; False when it was dropped (link down or backlog).

        WS3.5 uses the return value to count stalls instead of failing a run.
        """
        if self.fn is None or self.q.qsize() > 2000:
            return False
        self.q.put_nowait((time.monotonic() + self.delay, d))
        return True
    def clear(self):
        while not self.q.empty():
            self.q.get_nowait()
    async def run(self):
        while True:
            t, d = await self.q.get()
            w = t - time.monotonic()
            if w > 0:
                await asyncio.sleep(w)
            fn = self.fn
            if fn is None:
                continue
            try:
                await fn(d)
            except (ConnectionClosed, OSError):
                pass


def broadcast(data, keyframe=True):
    """Queue a frame for each Z.

    JPEG frames are independent, so keyframe=True clears the queue and keeps
    only the newest frame. H.264 frames are queued as a GOP so a P-frame is
    never sent without the keyframe it depends on.
    """
    global y_force_key
    y_frame_times.append(time.monotonic())
    dropped = False
    for slot in zs.values():
        q = slot["queue"]
        if keyframe:
            q.clear()
        q.append(data)
        if len(q) > 30:                 # ~1 s at 30 fps; wait for the next keyframe
            q.clear()
            dropped = True
        slot["ev"].set()
    if dropped and isinstance(data, (bytes, bytearray)):
        # A queue overflow is a real application-level drop: recover with an IDR
        # instead of waiting for the next scheduled GOP keyframe.
        if data[:1] == b"x" and up is not None and up.fn is not None:
            up.put(json.dumps({"t": "need_idr"}))
        elif data[:1] == b"y":
            y_force_key = True


def all_h264():
    """True only when every connected Z advertised H.264 support."""
    return bool(zs) and all(slot["h264"] for slot in zs.values())


def send_caps():
    """Tell X whether it may send H.264 instead of JPEG."""
    global last_caps
    caps = all_h264()
    if up is not None and up.fn is not None and caps != last_caps:
        last_caps = caps
        up.put(json.dumps({"t": "caps", "h264": caps}))
        print(f"X stream codec: {'H.264' if caps else 'JPEG'}")


def send_stream():
    """Tell X to pause/resume video while Y is (or is not) in fallback."""
    global last_stream
    on = state["mode"] == "X"
    if up is not None and up.fn is not None and on != last_stream:
        last_stream = on
        up.put(json.dumps({"t": "stream", "on": on}))
        print(f"[{time.strftime('%X')}] X video: "
              f"{'streaming' if on else 'paused (EDGE Y)'}")


def send_x_control(payload):
    """Send one control message to Cloud X; False when the link is down (WS2.3)."""
    if up is None or up.fn is None:
        return False
    up.put(json.dumps(payload))
    return True


async def _lb_timeout(ws):
    """Answer a leaderboard request that X never answered (WS3.4 guard)."""
    try:
        await asyncio.sleep(2.5)
    except asyncio.CancelledError:
        return
    if lb_pending.pop(ws, None) is None:
        return
    try:
        await ws.send(json.dumps({"t": "leaderboard", "rows": [],
                                  "error": "L did not answer within 2.5 s "
                                           "(is Cloud X running the current "
                                           "build?)"}))
    except (ConnectionClosed, OSError):
        pass


def submit_score():
    """WS3.4: L is pinned to X, so Y routes the finished match's score there."""
    name = os.environ.get("FYP_PLAYER", "player")
    placement = ""
    source = "manual"
    if test_runner is not None and test_runner.plan is not None:
        placement = test_runner.plan.placement
        source = "test"
    entry = {"name": name, "score": int(game.score),
             "deaths": int(game.deaths), "workload": game.workload.name,
             "seed": game.seed, "placement": placement, "source": source}
    if send_x_control({"t": "task", "id": "L", "op": "submit", "entry": entry}):
        print(f"[{time.strftime('%X')}] L submit: {entry['score']} "
              f"({entry['workload']}, {source})")
    else:
        print(f"[{time.strftime('%X')}] L submit skipped: Cloud X is not linked")



async def z_sender(ws, slot, lock):
    try:
        while True:
            await slot["ev"].wait()
            slot["ev"].clear()
            while slot["ctl"]:             # test/control messages jump the frame queue
                data = slot["ctl"].popleft()
                async with lock:
                    await ws.send(data)
            while slot["queue"]:
                data = slot["queue"].popleft()
                async with lock:           # frames and pong replies share the socket
                    await ws.send(data)
    except (ConnectionClosed, OSError):
        pass


def update_mode():
    global bad, good_since, y_force_key
    override = state.get("mode_override")
    if override in ("X", "Y"):
        if state["mode"] != override:
            state["mode"] = override
            bad, good_since = 0, None
            if override == "Y":
                y_force_key = True      # first edge frame must be an IDR
            print(f"[{time.strftime('%X')}] MODE OVERRIDE -> {override}")
            send_stream()
        return
    r = state["rtt"]
    if state["mode"] == "X":
        bad = bad + 1 if r > C.HIGH_MS else 0
        if bad >= C.BAD_COUNT:
            state["mode"], bad, good_since = "Y", 0, None
            y_force_key = True          # the first EDGE Y frame must be an IDR
            print(f"[{time.strftime('%X')}] SWITCH X -> Y (rtt={r:.0f} ms)")
            send_stream()               # stop the cloud video: nobody displays it
    else:
        if r < C.LOW_MS:
            good_since = good_since or time.monotonic()
            if time.monotonic() - good_since > C.RECOVER_S:
                state["mode"], bad = "X", 0
                print(f"[{time.strftime('%X')}] SWITCH Y -> X (rtt={r:.0f} ms)")
                send_stream()           # resume the cloud video
        else:
            good_since = None


async def on_x_msg(msg):               # message from X, AFTER the simulated downlink delay
    global last_fwd
    if isinstance(msg, bytes):
        parsed = P.parse_pixels(msg) if chain is not None else None
        if parsed is not None:
            # WS3.5: D on X, E here — run the encoder on the received pixels.
            tick, seq, fmt, size, snapshot, data = parsed
            chain_stats.set_pixel_format(fmt)
            if snapshot is not None:
                game.restore(snapshot, effects=False)
            state["tick"] = game.tick
            state["game"] = game_summary()
            apply_stage("E", "", seq, {"surface": None}, (fmt, size, data))
            return
        # X frames already carry their source byte: JPEG is 'X', H.264 is 'x'.
        src = msg[0:1]
        if src == b"x":                 # x | key | tick | seq | payload
            tick = struct.unpack("!I", msg[2:6])[0]
            key = bool(msg[1])
        elif src == b"X":               # X | tick | seq | payload
            tick = struct.unpack("!I", msg[1:5])[0]
            key = True
        else:
            return                      # unknown marker: ignore rather than mis-parse
        state["lag"] = game.tick - tick
        x_frame_times.append(time.monotonic())
        if state["mode"] == "X" and tick > last_fwd:
            last_fwd = tick
            broadcast(msg, keyframe=key)
    else:
        m = json.loads(msg)
        if m["t"] == "stage" and chain is not None:
            # WS3.5: X forwarded the tick to a stage that lives here.
            try:
                stage, tick, seq, keys, snapshot = P.parse_stage(m)
            except P.PipelineError as exc:
                print(f"bad stage message: {exc}")
                return
            run_chain(stage, keys, seq, snapshot)
        elif m["t"] == "final":
            # WS3.5: the chain finished elsewhere; keep our copy current.
            if m.get("s") is not None:
                game.restore(m["s"], effects=False)
                state["tick"] = game.tick
                state["game"] = game_summary()
                chain_stats.mirror(len(msg))
        elif m["t"] == "pong":
            rtt = (time.monotonic() - m["ts"]) * 1000
            state["rtt"] = 0.7 * state["rtt"] + 0.3 * rtt if state["rtt"] else rtt
            update_mode()
        elif m["t"] == "need_snap":
            up.put(json.dumps({"t": "snap", "s": game.snapshot(),
                               "config": game.config}))
        elif m["t"] == "game_over":
            state["playing"] = False
            broadcast(json.dumps(m), keyframe=True)
            print(f"game over: score={m.get('score')}")
            submit_score()
            if test_runner is not None:
                test_runner.on_game_over()
        elif m["t"] == "task_result" and m.get("id") == "L":
            # WS3.4: L lives on X; forward the answer to Z's U view.
            for waiter in list(lb_pending):
                task = lb_pending.pop(waiter, None)
                if task is not None:
                    task.cancel()
            if m.get("ok"):
                state["leaderboard"] = m.get("rows") or []
                broadcast(json.dumps({"t": "leaderboard",
                                      "rows": state["leaderboard"],
                                      "count": m.get("count", len(state["leaderboard"]))}))
            else:
                broadcast(json.dumps({"t": "leaderboard", "rows": [],
                                      "error": m.get("error") or "L error"}))
                print(f"L error: {m.get('error')}")
        elif m["t"] == "x_stats":
            # WS2.3: 1 Hz encoder summary from Cloud X.
            encoder = {key: value for key, value in m.items()
                       if key not in ("t", "chain")}
            if encoder:
                state["x_stats"] = encoder
            if m.get("chain") is not None:
                state["x_channels"] = m["chain"]      # WS3.5 counters from X
        elif m["t"] == "video_ok":
            state["x_video"] = {key: value for key, value in m.items()
                                if key != "t"}
            if test_runner is not None:
                test_runner.on_video_ok(state["x_video"])
            print(f"[{time.strftime('%X')}] X video applied: "
                  f"{state['x_video'].get('size')} GOP "
                  f"{state['x_video'].get('gop')}, "
                  f"intra-refresh={state['x_video'].get('intra_refresh')}")
        elif m["t"] == "stopped":
            print(f"[{time.strftime('%X')}] X stopped by request")
        elif m["t"] == "placement_ok":
            # WS3.1: Cloud X confirms the tasks Y's router gave it.
            state["x_placement"] = dict(m.get("tasks") or {})
            state["placement_applied"] = True
            state["x_build"] = str(m.get("x") or "")
            state["x_chain"] = bool(m.get("custom"))
            if chain is not None and not state["x_chain"]:
                # A pre-WS3.5 X accepts the table but keeps its preset path,
                # so the chain would silently run on one tier (WAN check).
                state["chain_warning"] = (
                    f"Cloud X ({state['x_build'] or 'unknown build'}) did not "
                    f"confirm chain support; pull X to ws3.5")
                print(f"[{time.strftime('%X')}] WARNING: "
                      f"{state['chain_warning']}")
            else:
                state["chain_warning"] = ""
            print(f"[{time.strftime('%X')}] X tasks: "
                  f"{', '.join(state['x_placement'])}" +
                  (f" (build {state['x_build']})" if state["x_build"] else ""))
        elif m["t"] == "error" and m.get("command") == "placement":
            state["placement_applied"] = False
            print(f"[{time.strftime('%X')}] placement rejected by X: "
                  f"{m.get('message')}")


async def tick_loop():
    global y_encoder, paused, y_force_key, edge_over_sent
    nxt = time.monotonic()
    while True:
        nxt += TICK
        if not state["playing"] or paused:
            await asyncio.sleep(TICK)
            nxt = time.monotonic()
            continue
        keys = inp["keys"]
        if inp["latch"] and " " not in keys:
            keys += " "                # a short tap between two ticks is not lost
        inp["latch"] = False
        seq = inp["seq"]
        if chain is not None:
            # WS3.5: a custom placement runs as a stage chain (see run_chain).
            chain_tick(keys, seq)
            now = time.monotonic()
            if nxt < now - 0.2:
                nxt = now
            await asyncio.sleep(max(0, nxt - now))
            continue
        # WS3.2: Y always runs A+B then C (same code as X), so the fallback copy
        # stays valid. For Offload A/B the post-A/B state is shipped to X
        # between the two phases, which is exactly the cost being measured.
        t_sim = time.perf_counter()
        game.step_ab(keys)
        task_stats.add("sim", (time.perf_counter() - t_sim) * 1000, "Y")
        if state.get("remote_ab"):
            payload = json.dumps({"t": "state", "tick": game.tick, "seq": seq,
                                  "keys": keys, "s": game.snapshot()})
            count_offload(len(payload))
            up.put(payload)
        t_hit = time.perf_counter()
        game.step_c()
        task_stats.add("hit", (time.perf_counter() - t_hit) * 1000, "Y")
        state["tick"] = game.tick
        state["game"] = {
            "hp": max(0, game.player.hp),
            "max_hp": game.player.max_hp,
            "bots": len(game.bots),
            "obstacles": len(game.obstacles),
            "bullets": len(game.bullets),
            "score": game.score,
            "deaths": game.deaths,
            "tick": game.tick,
            "workload": game.workload.name,
        }
        if state.get("edge_only"):
            # All Edge: X owns only L, so there is no frame pipeline to feed.
            if game.game_over and not edge_over_sent:
                edge_over_sent = True
                state["playing"] = False
                broadcast(json.dumps({"t": "game_over", "score": game.score,
                                      "deaths": game.deaths}), keyframe=True)
                print(f"game over (edge): score={game.score}")
                submit_score()
                if test_runner is not None:
                    test_runner.on_game_over()
        else:
            up.put(json.dumps({"t": "in", "tick": game.tick, "keys": keys,
                               "seq": seq}))
        if state["mode"] == "Y" and game.tick % C.Y_STREAM_EVERY == 0:
            if y_encoder is not None and all_h264():
                try:
                    if y_force_key:
                        y_encoder.force_keyframe()
                        y_force_key = False
                    t_render = time.perf_counter()
                    frame = game.render_surface(C.Y_SIZE, smooth=False)
                    t_encode = time.perf_counter()
                    packets = y_encoder.encode_surface(frame)
                    task_stats.add("render", (t_encode - t_render) * 1000, "Y")
                    task_stats.add("encode",
                                   (time.perf_counter() - t_encode) * 1000, "Y")
                    for payload, key in packets:
                        # Lowercase 'y' marks H.264; byte 1 is the keyframe flag.
                        broadcast(b"y" + bytes([1 if key else 0])
                                  + struct.pack("!II", game.tick, seq) + payload,
                                  keyframe=key)
                except Exception as exc:          # keep the tier alive
                    print(f"H.264 encode failed ({exc!r}); falling back to JPEG")
                    y_encoder = None
                    broadcast(b"Y" + struct.pack("!II", game.tick, seq)
                              + game.render(C.Y_SIZE, C.Y_QUALITY, smooth=False),
                              keyframe=True)
            else:
                broadcast(b"Y" + struct.pack("!II", game.tick, seq)
                          + game.render(C.Y_SIZE, C.Y_QUALITY, smooth=False),
                          keyframe=True)
        now = time.monotonic()
        if nxt < now - 0.2:
            nxt = now                  # fell far behind: don't try to catch up
        await asyncio.sleep(max(0, nxt - now))


async def ping_loop():
    while True:
        now = time.monotonic()
        if up is not None and up.fn is not None:
            up.put(json.dumps({"t": "ping", "ts": now}))
        state["x_fps"] = window_fps(x_frame_times, now)
        state["y_fps"] = window_fps(y_frame_times, now)
        refresh_task_stats()
        if test_runner is not None:
            test_runner.tick(now)
        log_w.writerow([round(time.time(), 3), state["mode"], round(state["rtt"], 1),
                        state["delay_ms"], round(state["e2e"], 1),
                        round(state["rtt_zy"], 1), int(state["linked"])])
        log_f.flush()
        await asyncio.sleep(0.2)


def set_delay(ms):
    """Set the injected X<->Y RTT delay (0..400 ms)."""
    state["delay_ms"] = max(0.0, min(400.0, float(ms)))
    if up is not None and down is not None:
        up.delay = down.delay = state["delay_ms"] / 2000   # one-way = RTT / 2


def window_fps(times, now):
    while times and times[0] < now - 1.0:
        times.popleft()
    return float(len(times))


def refresh_task_stats():
    """Merge Y's per-task timings with X's p50s and the measured hops (WS3.1)."""
    state["task_stats"] = merge_metrics(task_stats.snapshot(),
                                        state.get("x_stats"),
                                        state.get("rtt"),
                                        state.get("rtt_zy"))
    if chain is not None:
        # WS3.5: crossings, bytes and stalls for the live panel + report.
        snap = chain_stats.snapshot()
        snap["state"] = chain.tasks
        snap["crossings"] = len(chain.crossings)
        snap["stream_tier"] = chain.stream_tier
        state["channels"] = snap
        state["stalls"] = snap["stalls"]


def send_to_z(data):
    """Queue a control message for every connected Z (bypasses frame batching)."""
    count = 0
    for slot in list(zs.values()):
        slot["ctl"].append(data)
        slot["ev"].set()
        count += 1
    return count


# ---------------------------------------------------------------------------
# WS3.5: custom stage chain on EDGE Y.
#
# A tick starts at the tier that owns A.  Each tier runs the longest local run
# of stages (``Chain.local_run``) and forwards at a crossing; D and E on
# different tiers ship rendered pixels (``p`` binary) instead of JSON state.
# The three presets keep their old, separately tested paths.
# ---------------------------------------------------------------------------
def chain_tick(keys, seq):
    """One tick of a custom placement, starting at A's owner."""
    entry = chain.first()
    if entry["tier"] == "Y":
        run_chain("A", keys, seq)
    else:
        payload = P.stage_message("A", game.tick + 1, seq, keys)
        chain_stats.crossing(P.STATE, len(payload))
        if up is None or not up.put(payload):
            chain_stats.stall(game.tick + 1)


def run_chain(stage, keys="", seq=0, snapshot=None, pixels=None):
    """Run Y's slice of the chain from ``stage``; returns True if it was ours."""
    run, forward = chain.local_run(stage, "Y")
    if not run:
        return False                     # another tier owns this stage
    if snapshot is not None:
        game.restore(snapshot, effects=False)
    frame = {"surface": None}
    for name in run:
        apply_stage(name, keys, seq, frame, pixels)
        if name == "E":
            pixels = None                # consumed by the local encoder
    state["tick"] = game.tick
    state["game"] = game_summary()
    if game.game_over and not edge_over_sent:
        on_chain_game_over()
    if forward is not None:
        forward_chain(forward, keys, seq, frame)
    return True


def apply_stage(name, keys, seq, frame, pixels=None):
    """Run one stage on Y and record its cost (WS3.5)."""
    t0 = time.perf_counter()
    if name == "A":
        game.step_a(keys)
    elif name == "B":
        game.step_b()
    elif name == "C":
        game.step_c()
    elif name == "D":
        frame["surface"] = game.render_surface(C.Y_SIZE, smooth=False)
    elif name == "E":
        stream_frame(seq, frame, pixels)
    chain_stats.stage(name, (time.perf_counter() - t0) * 1000)
    if name in ("A", "B"):
        task_stats.add("sim", (time.perf_counter() - t0) * 1000, "Y")
    elif name == "C":
        task_stats.add("hit", (time.perf_counter() - t0) * 1000, "Y")
    elif name == "D":
        task_stats.add("render", (time.perf_counter() - t0) * 1000, "Y")


def forward_chain(forward, keys, seq, frame):
    """Ship the tick to the other tier: pixels for D->E, JSON state otherwise."""
    if forward == "E":
        data, fmt, size = offload_pixels(frame)
        payload = P.pixels_message(game.tick, seq, fmt, size,
                                   game.snapshot(), data)
    else:
        payload = P.stage_message(forward, game.tick, seq, keys,
                                  game.snapshot())
    chain_stats.crossing(P.PIXELS if forward == "E" else P.STATE, len(payload))
    if up is None or not up.put(payload):
        chain_stats.stall(game.tick)


def offload_pixels(frame):
    """Pixels for the D->E crossing: ``(bytes, fmt, size)``.

    JPEG keeps the link at 40-90 KB per frame; ``FYP_PIXELS_RAW=1`` sends the
    RGBA surface instead (lossless, ~2.8 MB at 720p) to show the stall cliff.
    """
    if PIXELS_RAW and frame.get("surface") is not None:
        import pygame
        surface = frame["surface"]
        fmt = P.pixel_format(raw=True)
        chain_stats.set_pixel_format(fmt)
        return pygame.image.tobytes(surface, "RGBA"), fmt, surface.get_size()
    fmt = P.pixel_format(quality=C.Y_QUALITY)
    chain_stats.set_pixel_format(fmt)
    return (game.render(C.Y_SIZE, C.Y_QUALITY, smooth=False), fmt, C.Y_SIZE)


def pixels_image(pixels):
    """Decode a D->E pixel payload into a PIL image for the H.264 encoder."""
    from PIL import Image
    fmt, size, data = pixels
    if fmt == "raw":
        return Image.frombytes("RGBA", (int(size[0]), int(size[1])),
                              data).convert("RGB")
    return Image.open(io.BytesIO(data)).convert("RGB")


def stream_frame(seq, frame, pixels=None):
    """E on Y: encode the tick (H.264 when every Z can decode) and broadcast.

    ``frame["surface"]`` is set when D also ran here; otherwise ``pixels`` is
    the (fmt, size, bytes) payload received from the tier that rendered.
    """
    global y_force_key, y_encoder
    tick = game.tick
    surface = frame.get("surface")
    if y_encoder is not None and all_h264() and (surface is not None or pixels):
        try:
            if y_force_key:
                y_encoder.force_keyframe()
                y_force_key = False
            t_enc = time.perf_counter()
            if surface is not None:
                packets = y_encoder.encode_surface(surface)
            else:
                packets = y_encoder.encode(pixels_image(pixels))
            ms = (time.perf_counter() - t_enc) * 1000
            task_stats.add("encode", ms, "Y")
            chain_stats.encoded(ms)
            for payload, key in packets:
                # Lowercase 'y' marks H.264; byte 1 is the keyframe flag.
                broadcast(b"y" + bytes([1 if key else 0])
                          + struct.pack("!II", tick, seq) + payload,
                          keyframe=key)
            return
        except Exception as exc:          # keep the tier alive
            print(f"H.264 encode failed ({exc!r}); falling back to JPEG")
            y_encoder = None
    if pixels is not None and len(pixels) == 3 and pixels[0] != "raw":
        jpeg = pixels[2]                  # already JPEG: only re-framed here
    else:
        jpeg = game.render(C.Y_SIZE, C.Y_QUALITY, smooth=False)
    chain_stats.encoded()
    broadcast(b"Y" + struct.pack("!II", tick, seq) + jpeg, keyframe=True)


def on_chain_game_over():
    """The custom chain finished the match: broadcast once and stop."""
    global edge_over_sent
    edge_over_sent = True
    state["playing"] = False
    broadcast(json.dumps({"t": "game_over", "score": game.score,
                          "deaths": game.deaths}), keyframe=True)
    print(f"game over (chain): score={game.score}")
    submit_score()
    if test_runner is not None:
        test_runner.on_game_over()


def game_summary():
    """Dashboard/panel view of the last executed tick."""
    return {
        "hp": max(0, game.player.hp),
        "max_hp": game.player.max_hp,
        "bots": len(game.bots),
        "obstacles": len(game.obstacles),
        "bullets": len(game.bullets),
        "score": game.score,
        "deaths": game.deaths,
        "tick": game.tick,
        "workload": game.workload.name,
    }


class TestRunner:
    """One measurement run: plan clock, timeline events, samples and report."""

    def __init__(self, directory):
        self.directory = directory
        self.plan = None
        self.phase = "idle"
        self.started_at = None
        self.started_mono = None
        self.measure_start = None
        self.finished_at = None
        self.finished_elapsed = 0.0
        self.report_id = None
        self.report_paths = None
        self.samples = []
        self.events = []
        self.applied = set()
        self.pause_started = None
        self.paused_total = 0.0
        self.last_sample = 0.0
        self.error = ""
        self.hold_actions = []
        self.reason = ""
        self.video_requested = None      # WS2.3: presets sent to Cloud X
        self.video_applied = None        # ... and what X confirmed

    def _mode_override(self):
        """Render tier: the placement's D tier when it is not legacy (WS3.1).

        WS3.5: a custom chain streams from E's tier, which is not D's tier when
        the pixels channel splits them; ``on_game_start`` re-applies this, so it
        must not fall back to D.
        """
        plan = self.plan
        if plan is None:
            return None
        table = plan.placement_table()
        if table is not None and plan.mode == "auto":
            if plan.placement == "custom":
                return Chain(table).stream_tier
            return render_tier(table)
        return plan.mode_override()

    # -- status ---------------------------------------------------------
    def _elapsed(self):
        if self.measure_start is None:
            return 0.0
        if self.phase == "finished":
            return max(0.0, self.finished_elapsed)
        return max(0.0, time.monotonic() - self.measure_start)

    def snapshot(self):
        now = time.monotonic()
        plan = self.plan
        elapsed = self._elapsed()
        warmup_left = 0.0
        if self.phase == "warmup" and self.measure_start is not None:
            warmup_left = max(0.0, self.measure_start - now)
        next_event = None
        if plan is not None:
            for index, event in enumerate(plan.sorted_events()):
                if index not in self.applied:
                    next_event = {"at_s": round(event.at_s, 2),
                                  "kind": event.kind,
                                  "value": event.value(),
                                  "label": event.label()}
                    break
        duration = plan.duration_s if plan else 0.0
        return {
            "state": self.phase,
            "name": plan.name if plan else "",
            "warmup_s": plan.warmup_s if plan else 0.0,
            "duration_s": duration,
            "elapsed_s": round(0.0 if self.phase == "warmup" else elapsed, 2),
            "warmup_left_s": round(warmup_left, 2),
            "remaining_s": round(max(0.0, duration - elapsed), 2),
            "progress": round(min(1.0, elapsed / duration), 3) if duration else 0.0,
            "mode": state.get("mode"),
            "mode_override": state.get("mode_override"),
            "pattern": plan.input_pattern if plan else "",
            "video_preset": plan.video_preset if plan else "",
            "next_event": next_event,
            "events": list(self.events),
            "report_id": self.report_id,
            "error": self.error,
        }

    def set_plan(self, raw):
        plan = TestPlan.from_dict(raw or {})
        if self.phase in ("starting", "warmup", "running", "paused"):
            raise PlanError("a test is already running")
        self.plan = plan
        state["test"] = self.snapshot()
        return plan

    # -- lifecycle ------------------------------------------------------
    async def start(self, raw):
        global paused, chain, chain_stats
        plan = TestPlan.from_dict(raw or {})
        if self.phase in ("starting", "warmup", "running", "paused"):
            raise PlanError("a test is already running")
        if not zs:
            raise PlanError("no End Z is connected")
        self.plan = plan
        self.phase = "starting"
        self.error = ""
        self.samples = []
        self.events = []
        self.applied = set()
        self.hold_actions = []
        self.pause_started = None
        self.paused_total = 0.0
        self.last_sample = 0.0
        self.finished_elapsed = 0.0
        self.started_at = time.time()
        self.started_mono = time.monotonic()
        self.measure_start = None
        self.finished_at = None
        self.reason = ""
        self.report_paths = None
        self.report_id = report_mod.new_id()
        paused = False
        offload_window.clear()
        offload.update(n=0, bytes=0, kb_s=0.0, total=0)
        state["offload"] = dict(offload)
        state["paused"] = False
        state["mode_override"] = self._mode_override()
        set_delay(0)
        update_mode()
        send_stream()
        # WS2.3: apply the preset and subscribe to X encoder stats. Both need
        # the X link; without it the preset is recorded in the report only.
        self.video_requested = plan.video_command()
        self.video_applied = None
        if state.get("linked"):
            if self.video_requested is not None:
                send_x_control(self.video_requested)
                print(f"[{time.strftime('%X')}] test: X video preset "
                      f"{plan.video_preset}")
            send_x_control({"t": "stats", "on": True})
        else:
            print(f"[{time.strftime('%X')}] test: Cloud X not linked; "
                  f"video preset {plan.video_preset} recorded only")
        # WS3.1: apply the plan's task placement and tell X which tasks it owns.
        table = plan.placement_table()
        state["placement"] = table or {}
        state["placement_pattern"] = plan.placement
        state["placement_applied"] = False
        state["chain_warning"] = ""        # WS3.5: cleared per run
        state["edge_only"] = edge_pipeline(table)
        # A/B on Y alone does not mean "ship the state up": with the whole
        # pipeline on Y (All Edge) X is idle, so there is nothing to upload.
        state["remote_ab"] = placement_remote_ab(table) and not state["edge_only"]
        # WS3.5: a custom table runs through the stage chain, not the presets.
        custom = plan.placement == "custom" and table is not None
        chain = Chain(table) if custom else None
        chain_stats = ChannelStats()
        if custom:
            state["edge_only"] = False      # the chain decides who steps/streams
            state["remote_ab"] = False
            state["chain"] = chain.pattern
            state["chain_crossings"] = len(chain.crossings)
            state["chain_desc"] = chain.describe()
            print(f"[{time.strftime('%X')}] test: custom chain "
                  f"{chain.describe()}")
        else:
            state["chain"] = {}
            state["chain_crossings"] = 0
            state["chain_desc"] = ""
        # Z must not ask for an IDR on every gap once a chain runs at an
        # irregular cadence (WS3.5 encoder-tick fix); 0 means "any stride".
        send_to_z(P.stride_message("x", 0 if custom else C.X_STREAM_EVERY))
        send_to_z(P.stride_message("y", 0 if custom else C.Y_STREAM_EVERY))
        if table is None:
            print(f"[{time.strftime('%X')}] test: placement legacy "
                  f"(whole-pipeline)")
        elif state.get("linked"):
            control = {"t": "placement", "tasks": dict(table)}
            if custom:
                control["custom"] = True
            send_x_control(control)
            print(f"[{time.strftime('%X')}] test: placement {plan.placement} "
                  f"({describe_placement(table)})")
        else:
            print(f"[{time.strftime('%X')}] test: Cloud X not linked; "
                  f"placement {plan.placement} recorded only")
        # A placement run must render where the pattern says; otherwise the
        # legacy RTT fallback would move D to Y and invalidate the measurement.
        if table is not None and plan.mode == "auto":
            state["mode_override"] = (chain.stream_tier if custom
                                      else render_tier(table))
            update_mode()
            send_stream()
            print(f"[{time.strftime('%X')}] test: rendering pinned to "
                  f"{state['mode_override']} by the placement")
        payload = {"t": "test", "cmd": "start", "workload": plan.workload,
                   "seed": plan.seed, "pattern": plan.input_pattern,
                   "plan": plan.name}
        if SAFE_TESTS:
            payload["safe"] = SAFE_TEST_CONFIG      # WS3.4.1: HP 1000, no damage
        if not send_to_z(json.dumps(payload)):
            self.phase = "error"
            self.error = "End Z is not reachable"
            state["test"] = self.snapshot()
            raise PlanError(self.error)
        state["test"] = self.snapshot()
        print(f"[{time.strftime('%X')}] test start: {plan.name} "
              f"({plan.warmup_s:g}+{plan.duration_s:g}s, {plan.workload}, "
              f"mode {plan.mode}, input {plan.input_pattern})")
        return plan

    def on_game_start(self):
        if self.plan is None:
            return
        if self.phase not in ("starting", "warmup"):
            return
        if self.measure_start is not None:
            return
        now = time.monotonic()
        self.measure_start = now + self.plan.warmup_s
        self.phase = "warmup"
        self.started_mono = now
        self.last_sample = 0.0
        state["mode_override"] = self._mode_override()
        update_mode()                  # re-apply a forced cloud/edge mode after start
        send_stream()
        state["test"] = self.snapshot()
        print(f"[{time.strftime('%X')}] test warm-up {self.plan.warmup_s:g}s")

    # -- timeline -------------------------------------------------------
    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        self.apply_holds(now)
        if self.phase == "starting":
            if self.started_mono is not None and now - self.started_mono > 8.0:
                self.fail("End Z did not start the match")
            state["test"] = self.snapshot()
            return
        if self.phase == "warmup":
            if self.measure_start is not None and now >= self.measure_start:
                self.phase = "running"
                self.last_sample = 0.0
                self.apply_due(0.0, now)
            state["test"] = self.snapshot()
            return
        if self.phase == "paused":
            state["test"] = self.snapshot()
            return
        if self.phase != "running":
            state["test"] = self.snapshot()
            return
        elapsed = max(0.0, now - self.measure_start)
        self.apply_due(elapsed, now)
        if self.phase != "running":
            state["test"] = self.snapshot()
            return
        if now - self.last_sample >= 0.2:
            self.last_sample = now
            self.samples.append(self.sample(elapsed))
        if elapsed >= self.plan.duration_s:
            self.finish()
            return
        state["test"] = self.snapshot()

    def apply_due(self, elapsed, now):
        if self.plan is None:
            return
        for index, event in enumerate(self.plan.sorted_events()):
            if index in self.applied or event.at_s > elapsed + 1e-6:
                continue
            self.applied.add(index)
            self.events.append({"elapsed_s": round(elapsed, 2),
                                "wall": round(time.time(), 3),
                                **event.to_dict()})
            if event.kind == "delay":
                set_delay(event.delay_ms)
                if event.hold_s is not None:
                    self.hold_actions.append((now + event.hold_s, "delay", 0))
            elif event.kind == "mode":
                state["mode_override"] = MODE_OVERRIDE.get(event.mode)
                update_mode()
                send_stream()
                if event.hold_s is not None:
                    self.hold_actions.append((now + event.hold_s, "mode", None))
            elif event.kind == "pattern":
                send_to_z(json.dumps({"t": "test", "cmd": "pattern",
                                      "pattern": event.pattern}))
                if event.hold_s is not None:
                    self.hold_actions.append((now + event.hold_s, "pattern", None))
            elif event.kind == "pause":
                self.pause("timeline")
                if event.hold_s is not None:
                    self.hold_actions.append((now + event.hold_s, "resume", None))
                break
            print(f"[{time.strftime('%X')}] test event: {event.label()} "
                  f"at {elapsed:g}s")

    def apply_holds(self, now):
        remaining = []
        for due, kind, value in self.hold_actions:
            if now < due:
                remaining.append((due, kind, value))
                continue
            if kind == "delay":
                set_delay(0)
            elif kind == "mode":
                state["mode_override"] = (self.plan.mode_override()
                                          if self.plan else None)
                update_mode()
                send_stream()
            elif kind == "pattern":
                if self.plan is not None:
                    send_to_z(json.dumps({"t": "test", "cmd": "pattern",
                                          "pattern": self.plan.input_pattern}))
            elif kind == "resume":
                self.resume()
        self.hold_actions = remaining

    def sample(self, elapsed):
        z_stats = state.get("z_stats") or {}
        x_stats = state.get("x_stats") or {}
        game_state = state.get("game") or {}
        return {
            "t": round(elapsed, 2),
            "wall": round(time.time(), 3),
            "phase": self.phase,
            "mode": state.get("mode"),
            "paused": self.phase == "paused",
            "rtt": round(float(state.get("rtt", 0.0)), 1),
            "delay": round(float(state.get("delay_ms", 0.0)), 1),
            "e2e": round(float(state.get("e2e", 0.0)), 1),
            "rtt_zy": round(float(state.get("rtt_zy", 0.0)), 1),
            "x_fps": round(float(state.get("x_fps", 0.0)), 1),
            "y_fps": round(float(state.get("y_fps", 0.0)), 1),
            "z_fps": round(float(z_stats.get("fps", 0.0)), 1),
            "x_encode": x_stats.get("encode_p50"),
            "x_encode_p95": x_stats.get("encode_p95"),
            "x_kf": x_stats.get("keyframes_s"),
            "z_decode": round(float(z_stats.get("decode", 0.0)), 1),
            "tick": int(game_state.get("tick", 0)),
            "score": int(game_state.get("score", 0)),
            "hp": int(game_state.get("hp", 0)),
        }


    def pause(self, reason="panel"):
        global paused
        if self.phase not in ("warmup", "running"):
            return
        if self.phase == "paused":
            return
        self.phase = "paused"
        self.pause_started = time.monotonic()
        paused = True
        state["paused"] = True
        up.put(json.dumps({"t": "pause"}))
        send_to_z(json.dumps({"t": "test", "cmd": "pause"}))
        state["test"] = self.snapshot()
        print(f"[{time.strftime('%X')}] test paused ({reason})")

    def resume(self):
        global paused
        if self.phase != "paused":
            return
        now = time.monotonic()
        held = max(0.0, now - (self.pause_started or now))
        self.paused_total += held
        if self.measure_start is not None:
            self.measure_start += held
        paused = False
        state["paused"] = False
        up.put(json.dumps({"t": "resume"}))
        send_to_z(json.dumps({"t": "test", "cmd": "resume"}))
        self.pause_started = None
        self.phase = ("warmup" if self.measure_start is not None
                      and now < self.measure_start else "running")
        state["test"] = self.snapshot()
        print(f"[{time.strftime('%X')}] test resumed")

    def stop(self, reason="panel"):
        global paused
        if self.phase in ("idle", "finished", "error"):
            return
        self.finished_elapsed = self._elapsed()
        self.phase = "finished"
        self.finished_at = time.time()
        self.reason = reason
        paused = False
        state["paused"] = False
        state["playing"] = False
        up.put(json.dumps({"t": "pause"}))
        send_x_control({"t": "stats", "on": False})
        send_to_z(json.dumps({"t": "test", "cmd": "stop"}))
        self.write_report(reason)
        state["test"] = self.snapshot()
        print(f"[{time.strftime('%X')}] test finished ({reason})")

    def finish(self):
        if self.phase == "running":
            self.finished_elapsed = max(0.0, time.monotonic() - self.measure_start)
        self.stop("duration")

    def fail(self, message):
        global paused
        self.error = str(message)
        self.phase = "error"
        self.finished_at = time.time()
        self.reason = "error"
        paused = False
        state["paused"] = False
        state["playing"] = False
        up.put(json.dumps({"t": "pause"}))
        send_to_z(json.dumps({"t": "test", "cmd": "stop"}))
        self.write_report("error")
        state["test"] = self.snapshot()
        print(f"[{time.strftime('%X')}] test error: {self.error}")

    def write_report(self, reason):
        if self.plan is None or self.report_id is None:
            return None
        ended = self.finished_at or time.time()
        started = self.started_at or ended
        environment = {
            "reason": reason,
            "thresholds": {"high_ms": C.HIGH_MS, "low_ms": C.LOW_MS,
                           "bad_count": C.BAD_COUNT,
                           "recover_s": C.RECOVER_S},
            "y_version": sys.version.split()[0],
            "video_preset": self.plan.video_preset,
            "video_runtime": ("applied (WS2.3)" if self.video_applied
                              else "current (fixed)"),
            "video_applied": self.video_applied,
            "video_requested": self.video_requested,
            "placement": self.plan.placement,
            "placement_table": state.get("placement") or {},
            "placement_applied": state.get("placement_applied", False),
            "task_stats": state.get("task_stats") or {},
            "offload": dict(offload),
            "paused_s": round(self.paused_total, 2),
            "game_config": getattr(game, "config", None),
            "mode_final": state.get("mode"),
        }
        channels = state.get("channels") or {}
        x_channels = state.get("x_channels") or {}
        # WS3.5: every report carries the chain keys; a preset run records
        # 0 crossings / 0 stalls instead of omitting them (compare tooling).
        pixels_fmt = (P.pixel_format(raw=PIXELS_RAW, quality=C.Y_QUALITY)
                      if chain is not None and chain.pixel_channel else None)
        encode_fps = None
        if chain is not None:
            encode_fps = ((channels.get("encode_frames") or 0)
                          + (x_channels.get("encode_frames") or 0)) \
                / max(0.001, self._elapsed() + self.plan.warmup_s)
        environment.update(P.report_fields(channels, x_channels, chain,
                                          pixels_fmt, encode_fps))
        try:
            report = report_mod.build(self.plan, started, ended, self.samples,
                                      self.events, environment,
                                      report_id=self.report_id)
            self.report_paths = report_mod.write(self.directory, report)
            state["reports"] = report_mod.list_reports(self.directory)
            print(f"[{time.strftime('%X')}] test report: "
                  f"{self.report_paths['json']}")
            return report
        except Exception as exc:
            self.error = f"could not write report: {exc!r}"
            print(self.error)
            return None

    def on_z_stats(self, stats):
        state["z_stats"] = dict(stats)
        if self.phase in ("starting", "warmup", "running", "paused"):
            state["test"] = self.snapshot()

    def on_video_ok(self, applied):
        """Cloud X confirmed a runtime video preset (WS2.3)."""
        self.video_applied = dict(applied or {})

    def on_game_over(self):
        if self.phase in ("starting", "warmup", "running", "paused"):
            self.stop("game over")


async def z_handler(ws):
    global game, last_fwd, bad, good_since, paused, y_force_key, edge_over_sent
    slot = {"queue": collections.deque(), "ev": asyncio.Event(),
            "h264": False, "ctl": collections.deque()}
    lock = asyncio.Lock()
    zs[ws] = slot
    sender = asyncio.create_task(z_sender(ws, slot, lock))
    print("Z connected")
    send_caps()          # treat a new Z as JPEG-only until it sends its hello
    try:
        async for msg in ws:
            m = json.loads(msg)
            if m.get("t") == "hello":
                slot["h264"] = bool(m.get("h264"))
                print(f"Z codec support: h264={slot['h264']}")
                send_caps()
                continue
            if m.get("t") == "pause":
                paused = True
                state["paused"] = True
                up.put(json.dumps({"t": "pause"}))
                print("game paused")
                continue
            if m.get("t") == "resume":
                paused = False
                state["paused"] = False
                up.put(json.dumps({"t": "resume"}))
                print("game resumed")
                continue
            if m.get("t") == "start":
                workload = m.get("workload", "light")
                seed = int(m.get("seed", 12345))
                config = m.get("config")
                try:
                    game = Game(workload, seed=seed, config=config)
                except Exception as exc:
                    print(f"invalid game config ({exc}); using defaults")
                    game = Game(workload, seed=seed)
                paused = False
                state["paused"] = False
                if y_encoder is not None:
                    y_encoder.force_keyframe()
                for slot in zs.values():
                    slot["queue"].clear()
                state.update(tick=0, mode="X", e2e=0.0, rtt_zy=0.0, lag=0,
                             playing=True)
                inp.update(keys="", seq=0, latch=False)
                last_fwd, bad, good_since = 0, 0, None
                y_force_key = False
                edge_over_sent = False
                if state.get("edge_only"):
                    # All Edge: X owns only L, so it gets neither start nor input.
                    send_stream()
                    print(f"[{time.strftime('%X')}] game start (edge only): "
                          f"X is idle, Y renders")
                else:
                    send_stream()           # a new game starts on the cloud tier
                    up.put(json.dumps({"t": "start", "workload": workload,
                                       "seed": seed, "config": game.config}))
                print(f"[{time.strftime('%X')}] game start requested: "
                      f"workload={workload} seed={seed} "
                      f"hp={game.player.max_hp} bots={game.workload.bots} "
                      f"obstacles={game.workload.obstacles}")
                if test_runner is not None:
                    test_runner.on_game_start()
                continue
            if m.get("t") == "version":
                # Lets Z tell an old Y apart from a broken leaderboard (WS3.4).
                await ws.send(json.dumps({"t": "version", "y": Y_BUILD,
                                          "leaderboard": True, "placement": True,
                                          "x_video": True}))
                continue
            if m.get("t") == "leaderboard_get":
                # WS3.4: Z asks for the top rows; L lives on X.
                top = m.get("top", 10)
                if not send_x_control({"t": "task", "id": "L", "op": "top",
                                       "top": top}):
                    await ws.send(json.dumps({
                        "t": "leaderboard", "rows": [],
                        "error": "Cloud X is not linked"}))
                    continue
                task = lb_pending.pop(ws, None)
                if task is not None:
                    task.cancel()
                lb_pending[ws] = asyncio.create_task(_lb_timeout(ws))
                continue
            if "keys" not in m:
                continue            # unknown control message: never kill the link
            inp["keys"], inp["seq"] = m["keys"], m["n"]
            state["e2e"] = m.get("e2e", 0.0)
            state["rtt_zy"] = m.get("rzy", state["rtt_zy"])
            if "fps" in m or "decode" in m:
                state["z_stats"] = {"fps": float(m.get("fps", 0.0)),
                                    "decode": float(m.get("decode", 0.0))}
            if m.get("want_idr"):               # Z lost a frame: recover immediately
                if state["mode"] == "Y" and y_encoder is not None:
                    y_force_key = True          # we are the sender in fallback
                else:
                    up.put(json.dumps({"t": "need_idr"}))
            if "pts" in m:                      # Z's Z<->Y latency probe: echo it back
                async with lock:
                    await ws.send(json.dumps({"t": "pong", "ts": m["pts"]}))
            if " " in m["keys"]:
                inp["latch"] = True
    finally:
        sender.cancel()
        zs.pop(ws, None)
        waiter = lb_pending.pop(ws, None)
        if waiter is not None:
            waiter.cancel()
        if not zs:
            inp["keys"] = ""           # do not keep steering after the player disconnects
            state["playing"] = False
        send_caps()


async def dash_handler(ws):
    panel = False

    async def tx():
        while True:
            await ws.send(json.dumps(state))
            await asyncio.sleep(0.2)

    t = asyncio.create_task(tx())
    try:
        async for raw in ws:
            try:
                m = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if not isinstance(m, dict):
                continue
            if m.get("cmd") == "hello":
                panel = True
                await ws.send(json.dumps({"t": "hello",
                                          "reports": state.get("reports", [])}))
                continue
            if "delay_ms" in m and "cmd" not in m:
                set_delay(m["delay_ms"])
                continue
            cmd = m.get("cmd")
            try:
                if cmd == "test_start":
                    if test_runner is None:
                        raise RuntimeError("test runner is not ready")
                    await test_runner.start(m.get("plan") or {})
                elif cmd == "test_pause":
                    if test_runner is not None:
                        test_runner.pause("panel")
                elif cmd == "test_resume":
                    if test_runner is not None:
                        test_runner.resume()
                elif cmd == "test_stop":
                    if test_runner is not None:
                        test_runner.stop("panel")
                elif cmd == "set_plan":
                    if test_runner is None:
                        raise RuntimeError("test runner is not ready")
                    test_runner.set_plan(m.get("plan") or {})
                elif cmd == "list_reports":
                    await ws.send(json.dumps({"t": "reports",
                                              "reports": state.get("reports", [])}))
                elif cmd == "get_report":
                    report = report_mod.load(REPORT_DIR, m.get("id"))
                    await ws.send(json.dumps({"t": "report", "report": report}))
                elif cmd == "placement":
                    # WS3.1: switch the router's placement live.
                    raw = m.get("tasks")
                    if raw is not None:
                        table = validate_placement(raw, require_all=True)
                        state["placement_pattern"] = "custom"
                    else:
                        name = str(m.get("pattern") or "").strip().lower()
                        table = pattern_table(name)
                        state["placement_pattern"] = name
                    state["placement"] = table or {}
                    state["placement_applied"] = False
                    state["edge_only"] = edge_pipeline(table)
                    state["remote_ab"] = (placement_remote_ab(table)
                                          and not state["edge_only"])
                    if table is None:
                        print(f"[{time.strftime('%X')}] placement: legacy "
                              f"whole-pipeline")
                    elif not send_x_control({"t": "placement",
                                             "tasks": dict(table)}):
                        raise RuntimeError("Cloud X is not linked")
                    else:
                        print(f"[{time.strftime('%X')}] placement: "
                              f"{describe_placement(table)}")
                elif cmd == "x_video":
                    # WS2.3: apply an A0/A1/A2/intra preset without restarting X.
                    payload = video_payload(m.get("preset"))
                    if payload is None:
                        raise ValueError(f"no runtime video preset "
                                         f"{m.get('preset')!r}; use A0/A1/A2/intra")
                    if not send_x_control(payload):
                        raise RuntimeError("Cloud X is not linked")
                elif cmd == "x_stats":
                    if not send_x_control({"t": "stats",
                                           "on": bool(m.get("on", True))}):
                        raise RuntimeError("Cloud X is not linked")
                elif cmd == "x_stop":
                    if not send_x_control({"t": "stop"}):
                        raise RuntimeError("Cloud X is not linked")
                elif cmd == "delay_ms":
                    set_delay(m.get("delay_ms", 0))
                else:
                    raise ValueError(f"unknown command {cmd!r}")
            except (PlanError, ValueError, OSError, RuntimeError) as exc:
                await ws.send(json.dumps({"t": "error", "command": cmd,
                                          "message": str(exc)}))
                if not panel:
                    print(f"dashboard command failed ({cmd}): {exc}")
    finally:
        t.cancel()


async def x_session():
    """One connection to Cloud X. Returns when the link closes."""
    global last_fwd, bad, good_since, last_caps, last_stream
    async with connect(C.X_URI, max_size=4 << 20, compression=None,
                       ping_interval=C.PING_INTERVAL, ping_timeout=C.PING_TIMEOUT) as xws:
        print(f"connected to X at {C.X_URI}")
        last_fwd, bad, good_since, last_caps, last_stream = 0, 0, None, None, None
        state["linked"], state["rtt"] = True, 0.0
        up.fn, down.fn = xws.send, on_x_msg
        up.delay = down.delay = state["delay_ms"] / 2000
        send_caps()                     # tell X which codec the connected Z can take
        send_stream()                   # and whether X should send video at all

        async def rx():
            async for m in xws:
                down.put(m)

        task = asyncio.create_task(rx())
        try:
            await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            state["linked"], state["rtt"] = False, 0.0   # do not show a stale RTT while DOWN
            up.fn = down.fn = None      # stop queueing; drop anything already in flight
            up.clear()
            down.clear()


async def main():
    global up, down, log_f, log_w, y_encoder, y_force_key, test_runner
    os.makedirs("logs", exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)
    test_runner = TestRunner(REPORT_DIR)
    state["reports"] = report_mod.list_reports(REPORT_DIR)
    log_f = open(os.path.join("logs", "log_y.csv"), "w", newline="")
    log_w = csv.writer(log_f)
    log_w.writerow(["unix_time", "mode", "rtt_ms", "injected_delay_ms",
                    "e2e_ms_from_Z", "rtt_zy_ms_from_Z", "x_link"])

    if C.Y_CODEC == "h264" and H264Encoder is not None:
        try:
            y_encoder = H264Encoder(C.Y_SIZE, C.Y_FPS, C.Y_BITRATE, C.Y_GOP,
                                    encoder=C.Y_ENCODER)
            print(f"Y fallback encoder: H.264 via {y_encoder.name} "
                  f"({C.Y_SIZE[0]}x{C.Y_SIZE[1]} @ {C.Y_FPS} fps, {C.Y_BITRATE} bps)")
        except Exception as exc:
            print(f"Y fallback encoder: H.264 unavailable ({exc}); using JPEG")
            y_encoder = None
    else:
        print("Y fallback encoder: JPEG (FYP_Y_CODEC=jpeg or PyAV missing)")

    up, down = DelayLine(), DelayLine()     # live for the whole process, attached per session
    loops = [asyncio.create_task(c) for c in (up.run(), down.run(), tick_loop(), ping_loop())]
    try:
        async with serve(z_handler, C.Y_HOST, C.Y_PORT_Z, max_size=4 << 20, compression=None,
                         ping_interval=C.PING_INTERVAL, ping_timeout=C.PING_TIMEOUT), \
                   serve(dash_handler, C.Y_HOST, C.Y_PORT_DASH, max_size=4 << 20, compression=None,
                         ping_interval=C.PING_INTERVAL, ping_timeout=C.PING_TIMEOUT):
            print(f"Y ready: Z -> ws://{lan_ip()}:{C.Y_PORT_Z}   dashboard -> ws://{lan_ip()}:{C.Y_PORT_DASH}")
            while True:
                try:
                    await x_session()
                    print("X link closed")
                except (OSError, ConnectionClosed) as e:
                    print(f"X link down ({e!r})")
                except Exception as e:                 # keep the tier alive whatever happens
                    print(f"X link error ({e!r})")
                state["linked"] = False
                if state["mode"] != "Y":               # keep playing on the edge while X is away
                    state["mode"] = "Y"
                    y_force_key = True
                    print(f"[{time.strftime('%X')}] SWITCH X -> Y (cloud link lost)")
                    send_stream()                      # no-op while X is down; resent on reconnect
                await asyncio.sleep(C.RECONNECT_S)
    finally:
        for t in loops:
            t.cancel()
        await asyncio.gather(*loops, return_exceptions=True)
        if y_encoder is not None:
            y_encoder.close()
        log_f.close()


try:
    asyncio.run(main())
except KeyboardInterrupt:
    pass
