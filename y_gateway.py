"""EDGE Y (laptop A): sequencer + fallback renderer + latency monitor + mode switch + dashboard backend."""
import asyncio, csv, json, struct, time
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from common import config as C
from common.win import hires_timer
hires_timer()
from common.game import Game

TICK = 1 / C.TICK_RATE
game = Game()
state = {"mode": "X", "rtt": 0.0, "lag": 0, "delay_ms": 0, "e2e": 0.0, "tick": 0}
inp = {"keys": "", "seq": 0, "latch": False}
zs = {}                # Z connection -> its "latest frame" slot
last_fwd, bad, good_since = 0, 0, None
up = down = None
log_f = log_w = None


class DelayLine:                       # simulated one-way network delay, order preserving
    def __init__(self, fn):
        self.q, self.fn, self.delay = asyncio.Queue(), fn, 0.0
    def put(self, d):
        self.q.put_nowait((time.monotonic() + self.delay, d))
    async def run(self):
        while True:
            t, d = await self.q.get()
            w = t - time.monotonic()
            if w > 0:
                await asyncio.sleep(w)
            await self.fn(d)


def broadcast(data):
    """Never blocks. Each Z only ever holds the NEWEST unsent frame (stale frames are dropped)."""
    for slot in zs.values():
        slot["data"] = data
        slot["ev"].set()


async def z_sender(ws, slot):
    while True:
        await slot["ev"].wait()
        slot["ev"].clear()
        data, slot["data"] = slot["data"], None
        if data is not None:
            await ws.send(data)


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
                state["mode"] = "X"
                print(f"[{time.strftime('%X')}] SWITCH Y -> X (rtt={r:.0f} ms)")
        else:
            good_since = None


async def on_x_msg(msg):               # message from X, AFTER the simulated downlink delay
    global last_fwd
    if isinstance(msg, bytes):
        tick = struct.unpack("!I", msg[:4])[0]
        state["lag"] = game.tick - tick
        if state["mode"] == "X" and tick > last_fwd:
            last_fwd = tick
            broadcast(b"X" + msg)
    else:
        m = json.loads(msg)
        if m["t"] == "pong":
            rtt = (time.monotonic() - m["ts"]) * 1000
            state["rtt"] = 0.7 * state["rtt"] + 0.3 * rtt if state["rtt"] else rtt
            update_mode()
        elif m["t"] == "need_snap":
            up.put(json.dumps({"t": "snap", "s": game.snapshot()}))


async def tick_loop():
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
            broadcast(b"Y" + struct.pack("!II", game.tick, seq) + game.render(C.Y_SIZE, C.Y_QUALITY, smooth=False))
        now = time.monotonic()
        if nxt < now - 0.2:
            nxt = now                  # fell far behind: don't try to catch up
        await asyncio.sleep(max(0, nxt - now))


async def ping_loop():
    while True:
        up.put(json.dumps({"t": "ping", "ts": time.monotonic()}))
        log_w.writerow([round(time.time(), 3), state["mode"], round(state["rtt"], 1), state["delay_ms"], round(state["e2e"], 1)])
        log_f.flush()
        await asyncio.sleep(0.2)


async def z_handler(ws):
    slot = {"data": None, "ev": asyncio.Event()}
    zs[ws] = slot
    sender = asyncio.create_task(z_sender(ws, slot))
    print("Z connected")
    try:
        async for msg in ws:
            m = json.loads(msg)
            inp["keys"], inp["seq"] = m["keys"], m["n"]
            state["e2e"] = m.get("e2e", 0.0)
            if " " in m["keys"]:
                inp["latch"] = True
    finally:
        sender.cancel()
        zs.pop(ws, None)


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
            up.delay = down.delay = ms / 2000      # one-way = RTT / 2
    finally:
        t.cancel()


async def main():
    global up, down, log_f, log_w
    log_f = open("log_y.csv", "w", newline="")
    log_w = csv.writer(log_f)
    log_w.writerow(["unix_time", "mode", "rtt_ms", "injected_delay_ms", "e2e_ms_from_Z"])
    async with connect(C.X_URI, max_size=None, compression=None, ping_interval=None) as xws:
        print("connected to X")
        up, down = DelayLine(xws.send), DelayLine(on_x_msg)
        async def rx():
            async for m in xws:
                down.put(m)
        async with serve(z_handler, "0.0.0.0", C.Y_PORT_Z, max_size=None, compression=None, ping_interval=None), \
                   serve(dash_handler, "0.0.0.0", C.Y_PORT_DASH):
            print("Y ready: waiting for Z and dashboard")
            await asyncio.gather(up.run(), down.run(), rx(), tick_loop(), ping_loop())

asyncio.run(main())
