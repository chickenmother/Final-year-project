"""EDGE Y (laptop A): sequencer + fallback renderer + latency monitor + mode switch + dashboard backend."""
import asyncio, collections, csv, json, struct, time
from websockets.exceptions import ConnectionClosed
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from common import config as C
from common.net import lan_ip, quiet_handshake_errors
from common.win import hires_timer
hires_timer()
quiet_handshake_errors()
from common.game import Game
try:
    from common.video import H264Encoder
except ImportError:                      # PyAV not installed: JPEG fallback
    H264Encoder = None

TICK = 1 / C.TICK_RATE
game = Game()
state = {"mode": "X", "rtt": 0.0, "rtt_zy": 0.0, "lag": 0, "delay_ms": 0,
         "e2e": 0.0, "tick": 0, "linked": False}
inp = {"keys": "", "seq": 0, "latch": False}
zs = {}                # Z connection -> frame queue + capability slot
last_fwd, bad, good_since = 0, 0, None
up = down = None
log_f = log_w = None
y_encoder = None       # H.264 encoder for the EDGE Y fallback stream
last_caps = None       # last H.264 capability advertised to X


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
    for slot in zs.values():
        q = slot["queue"]
        if keyframe:
            q.clear()
        q.append(data)
        if len(q) > 30:                 # ~1 s at 30 fps; wait for the next keyframe
            q.clear()
        slot["ev"].set()


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


async def z_sender(ws, slot, lock):
    try:
        while True:
            await slot["ev"].wait()
            slot["ev"].clear()
            while slot["queue"]:
                data = slot["queue"].popleft()
                async with lock:           # frames and pong replies share the socket
                    await ws.send(data)
    except (ConnectionClosed, OSError):
        pass


def update_mode():
    global bad, good_since
    r = state["rtt"]
    if state["mode"] == "X":
        bad = bad + 1 if r > C.HIGH_MS else 0
        if bad >= C.BAD_COUNT:
            state["mode"], bad, good_since = "Y", 0, None
            print(f"[{time.strftime('%X')}] SWITCH X -> Y (rtt={r:.0f} ms)")
    else:
        if r < C.LOW_MS:
            good_since = good_since or time.monotonic()
            if time.monotonic() - good_since > C.RECOVER_S:
                state["mode"], bad = "X", 0
                print(f"[{time.strftime('%X')}] SWITCH Y -> X (rtt={r:.0f} ms)")
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
            up.put(json.dumps({"t": "snap", "s": game.snapshot()}))


async def tick_loop():
    global y_encoder
    nxt = time.monotonic()
    while True:
        nxt += TICK
        keys = inp["keys"]
        if inp["latch"] and " " not in keys:
            keys += " "                # a short tap between two ticks is not lost
        inp["latch"] = False
        seq = inp["seq"]
        game.step(keys)                # Y ALWAYS runs the game (same code as X) -> instant fallback
        state["tick"] = game.tick
        up.put(json.dumps({"t": "in", "tick": game.tick, "keys": keys, "seq": seq}))
        if state["mode"] == "Y" and game.tick % C.Y_STREAM_EVERY == 0:
            if y_encoder is not None and all_h264():
                try:
                    img = game.render_image(C.Y_SIZE, smooth=False)
                    for payload, key in y_encoder.encode(img):
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
        if up is not None and up.fn is not None:
            up.put(json.dumps({"t": "ping", "ts": time.monotonic()}))
        log_w.writerow([round(time.time(), 3), state["mode"], round(state["rtt"], 1),
                        state["delay_ms"], round(state["e2e"], 1),
                        round(state["rtt_zy"], 1), int(state["linked"])])
        log_f.flush()
        await asyncio.sleep(0.2)


async def z_handler(ws):
    slot = {"queue": collections.deque(), "ev": asyncio.Event(), "h264": False}
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
            inp["keys"], inp["seq"] = m["keys"], m["n"]
            state["e2e"] = m.get("e2e", 0.0)
            state["rtt_zy"] = m.get("rzy", state["rtt_zy"])
            if m.get("want_idr"):               # Z lost a frame: ask X for a keyframe
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
        send_caps()


async def dash_handler(ws):
    async def tx():
        while True:
            await ws.send(json.dumps(state))
            await asyncio.sleep(0.2)
    t = asyncio.create_task(tx())
    try:
        async for m in ws:
            ms = float(json.loads(m)["delay_ms"])
            state["delay_ms"] = ms
            if up is not None and down is not None:
                up.delay = down.delay = ms / 2000      # one-way = RTT / 2
    finally:
        t.cancel()


async def x_session():
    """One connection to Cloud X. Returns when the link closes."""
    global last_fwd, bad, good_since, last_caps
    async with connect(C.X_URI, max_size=4 << 20, compression=None,
                       ping_interval=C.PING_INTERVAL, ping_timeout=C.PING_TIMEOUT) as xws:
        print(f"connected to X at {C.X_URI}")
        last_fwd, bad, good_since, last_caps = 0, 0, None, None
        state["linked"], state["rtt"] = True, 0.0
        up.fn, down.fn = xws.send, on_x_msg
        up.delay = down.delay = state["delay_ms"] / 2000
        send_caps()                     # tell X which codec the connected Z can take

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
    global up, down, log_f, log_w, y_encoder
    log_f = open("log_y.csv", "w", newline="")
    log_w = csv.writer(log_f)
    log_w.writerow(["unix_time", "mode", "rtt_ms", "injected_delay_ms",
                    "e2e_ms_from_Z", "rtt_zy_ms_from_Z", "x_link"])

    if C.Y_CODEC == "h264" and H264Encoder is not None:
        try:
            y_encoder = H264Encoder(C.Y_SIZE, C.Y_FPS, C.Y_BITRATE, C.Y_GOP)
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
                    print(f"[{time.strftime('%X')}] SWITCH X -> Y (cloud link lost)")
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
