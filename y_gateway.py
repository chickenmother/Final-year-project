"""EDGE Y (laptop A): sequencer + fallback renderer + latency monitor + mode switch + dashboard backend."""
import asyncio, collections, csv, json, os, struct, sys, time
from websockets.exceptions import ConnectionClosed
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from common import config as C
from common import report as report_mod
from common.net import lan_ip, quiet_handshake_errors
from common.testplan import MODE_OVERRIDE, PlanError, TestPlan
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
         "z_stats": {}, "x_stats": {}, "x_fps": 0.0, "y_fps": 0.0,
         "reports": []}
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
REPORT_DIR = os.path.join("logs", "reports")



class DelayLine:                       # simulated one-way network delay, order preserving
    """fn is the current sink (xws.send / on_x_msg). While it is None the line
    is disconnected and messages are dropped instead of piling up."""
    def __init__(self):
        self.q, self.fn, self.delay = asyncio.Queue(), None, 0.0
    def put(self, d):
        if self.fn is None or self.q.qsize() > 2000:
            return
        self.q.put_nowait((time.monotonic() + self.delay, d))
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
        if m["t"] == "pong":
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
            if test_runner is not None:
                test_runner.on_game_over()


async def tick_loop():
    global y_encoder, paused, y_force_key
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
        game.step(keys)                # Y ALWAYS runs the game (same code as X) -> instant fallback
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
        up.put(json.dumps({"t": "in", "tick": game.tick, "keys": keys, "seq": seq}))
        if state["mode"] == "Y" and game.tick % C.Y_STREAM_EVERY == 0:
            if y_encoder is not None and all_h264():
                try:
                    if y_force_key:
                        y_encoder.force_keyframe()
                        y_force_key = False
                    frame = game.render_surface(C.Y_SIZE, smooth=False)
                    for payload, key in y_encoder.encode_surface(frame):
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


def send_to_z(data):
    """Queue a control message for every connected Z (bypasses frame batching)."""
    count = 0
    for slot in list(zs.values()):
        slot["ctl"].append(data)
        slot["ev"].set()
        count += 1
    return count


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
        global paused
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
        state["paused"] = False
        state["mode_override"] = plan.mode_override()
        set_delay(0)
        update_mode()
        send_stream()
        payload = {"t": "test", "cmd": "start", "workload": plan.workload,
                   "seed": plan.seed, "pattern": plan.input_pattern,
                   "plan": plan.name}
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
        state["mode_override"] = self.plan.mode_override()
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
            "video_runtime": "current (fixed until WS2.3)",
            "paused_s": round(self.paused_total, 2),
            "game_config": getattr(game, "config", None),
            "mode_final": state.get("mode"),
        }
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

    def on_game_over(self):
        if self.phase in ("starting", "warmup", "running", "paused"):
            self.stop("game over")


async def z_handler(ws):
    global game, last_fwd, bad, good_since, paused, y_force_key
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
                state.update(tick=0, mode="X", e2e=0.0, rtt_zy=0.0, lag=0, playing=True)
                inp.update(keys="", seq=0, latch=False)
                last_fwd, bad, good_since = 0, 0, None
                y_force_key = False
                send_stream()               # a new game starts on the cloud tier
                up.put(json.dumps({"t": "start", "workload": workload, "seed": seed,
                                   "config": game.config}))
                print(f"[{time.strftime('%X')}] game start requested: "
                      f"workload={workload} seed={seed} "
                      f"hp={game.player.max_hp} bots={game.workload.bots} "
                      f"obstacles={game.workload.obstacles}")
                if test_runner is not None:
                    test_runner.on_game_start()
                continue
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
