"""CLOUD X (the cloud tier). Runs the full game, renders high quality, streams to Y."""
import asyncio, collections, csv, json, struct, time
from websockets.asyncio.server import serve
from common import config as C
from common.net import lan_ip, quiet_handshake_errors
from common.win import hires_timer
hires_timer()
quiet_handshake_errors()
from common.game import Game

game = Game()
resync = False
log_f = log_w = None
n_logged = 0


def log_frame(tick, seq, render_ms, nbytes):
    global n_logged
    log_w.writerow([round(time.time(), 3), tick, seq, round(render_ms, 1), nbytes])
    n_logged += 1
    if n_logged % 30 == 0:
        log_f.flush()


async def handler(ws):
    global resync
    # Do NOT reset the game on connect: ask Y for its snapshot instead, so the
    # two tiers converge on whichever side kept the newer state. This also
    # survives a Y or X restart without a visible jump.
    resync, need_at = True, time.monotonic()
    print(f"Y connected from {ws.remote_address}")
    lock = asyncio.Lock()

    async def send(data):                 # one writer at a time (frames + control share the socket)
        async with lock:
            await ws.send(data)

    await send(json.dumps({"t": "need_snap"}))

    q, ev = collections.deque(), asyncio.Event()
    out = {"data": None, "ev": asyncio.Event()}

    async def reader():                   # keeps reading even while we are busy rendering
        try:
            async for msg in ws:
                q.append(msg)
                ev.set()
        finally:
            ev.set()

    async def sender():                   # newest frame wins; a slow link never stalls the message pump
        while True:
            await out["ev"].wait()
            out["ev"].clear()
            data, out["data"] = out["data"], None
            if data is not None:
                await send(data)

    rd = asyncio.create_task(reader())
    sd = asyncio.create_task(sender())
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
                game.restore(m["s"])
                resync = False
                print(f"resynced at tick {game.tick}")
            elif t == "in":
                if m["tick"] == game.tick + 1:
                    game.step(m["keys"])
                    # if we are behind (inputs waiting), skip rendering so we catch up fast
                    if game.tick % C.X_STREAM_EVERY == 0 and len(q) < 3:
                        t0 = time.perf_counter()
                        jpg = game.render(C.X_SIZE, C.X_QUALITY)
                        log_frame(game.tick, m["seq"], (time.perf_counter() - t0) * 1000, len(jpg))
                        out["data"] = struct.pack("!II", game.tick, m["seq"]) + jpg
                        out["ev"].set()
                elif m["tick"] > game.tick + 1 and (not resync or time.monotonic() - need_at > 2.0):
                    resync, need_at = True, time.monotonic()
                    await send(json.dumps({"t": "need_snap"}))
    finally:
        rd.cancel()
        sd.cancel()
        await asyncio.gather(rd, sd, return_exceptions=True)
        print("Y disconnected")


async def main():
    global log_f, log_w
    log_f = open("log_x.csv", "w", newline="")
    log_w = csv.writer(log_f)
    log_w.writerow(["unix_time", "tick", "seq", "render_ms", "jpeg_bytes"])
    try:
        async with serve(handler, C.X_HOST, C.X_PORT, max_size=4 << 20, compression=None,
                         ping_interval=C.PING_INTERVAL, ping_timeout=C.PING_TIMEOUT):
            print(f"X ready: ws://{lan_ip()}:{C.X_PORT}  (listening on {C.X_HOST}:{C.X_PORT})")
            await asyncio.Future()
    finally:
        log_f.close()


try:
    asyncio.run(main())
except KeyboardInterrupt:
    pass
