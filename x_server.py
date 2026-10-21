"""CLOUD X  (desktop).  Runs the full game, renders high quality."""
import asyncio, collections, json, struct
from websockets.asyncio.server import serve
from common import config as C
from common.win import hires_timer
hires_timer()
from common.game import Game

game = Game()
resync = False

async def handler(ws):
    global game, resync
    game, resync = Game(), False          # a (re)connecting Y always starts at tick 0
    print("Y connected")
    q, ev = collections.deque(), asyncio.Event()

    async def reader():                   # keeps reading even while we are busy rendering
        try:
            async for msg in ws:
                q.append(msg)
                ev.set()
        finally:
            ev.set()

    task = asyncio.create_task(reader())
    try:
        while True:
            if not q:
                if task.done():
                    break
                ev.clear()
                await ev.wait()
                continue
            m = json.loads(q.popleft())
            t = m["t"]
            if t == "ping":
                await ws.send(json.dumps({"t": "pong", "ts": m["ts"]}))
            elif t == "snap":
                game.restore(m["s"]); resync = False
            elif t == "in":
                if m["tick"] == game.tick + 1:
                    game.step(m["keys"])
                    # if we are behind (inputs waiting), skip rendering so we catch up fast
                    if game.tick % C.X_STREAM_EVERY == 0 and len(q) < 3:
                        await ws.send(struct.pack("!II", game.tick, m["seq"]) + game.render(C.X_SIZE, C.X_QUALITY))
                elif m["tick"] > game.tick + 1 and not resync:
                    resync = True
                    await ws.send(json.dumps({"t": "need_snap"}))
    finally:
        task.cancel()

async def main():
    async with serve(handler, "0.0.0.0", C.X_PORT, max_size=None, compression=None, ping_interval=None):
        print(f"X ready on port {C.X_PORT}")
        await asyncio.Future()

asyncio.run(main())
