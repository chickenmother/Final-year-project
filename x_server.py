"""CLOUD X (the cloud tier). Runs the full game, renders high quality, streams to Y."""
import asyncio, collections, csv, json, struct, time
from websockets.asyncio.server import serve
from common import config as C
from common.net import lan_ip, quiet_handshake_errors
from common.win import hires_timer
hires_timer()
quiet_handshake_errors()
from common.game import Game
try:
    from common.video import H264Encoder
except ImportError:                      # PyAV not installed: JPEG only
    H264Encoder = None

game = Game()
resync = False
x_encoder = None
log_f = log_w = None
n_logged = 0


def log_frame(tick, seq, codec, encode_ms, nbytes):
    global n_logged
    log_w.writerow([round(time.time(), 3), tick, seq, codec,
                    round(encode_ms, 1), nbytes])
    n_logged += 1
    if n_logged % 30 == 0:
        log_f.flush()


async def handler(ws):
    global resync, x_encoder
    # Do NOT reset the game on connect: ask Y for its snapshot instead, so the
    # two tiers converge on whichever side kept the newer state. This also
    # survives a Y or X restart without a visible jump.
    resync, need_at = True, time.monotonic()
    z_h264, force_key = False, True
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
            elif t == "caps":
                # Y reports whether every connected Z can decode H.264.
                new = bool(m.get("h264"))
                if new != z_h264:
                    print(f"[{time.strftime('%X')}] X stream codec: "
                          f"{'H.264' if new else 'JPEG'}")
                    z_h264, force_key = new, new
            elif t == "need_idr":
                force_key = True
            elif t == "in":
                if m["tick"] == game.tick + 1:
                    game.step(m["keys"])
                    # if we are behind (inputs waiting), skip rendering so we catch up fast
                    if game.tick % C.X_STREAM_EVERY == 0 and len(q) < 3:
                        seq = m["seq"]
                        t0 = time.perf_counter()
                        if x_encoder is not None and z_h264:
                            try:
                                img = game.render_image(C.X_SIZE, True)
                                if force_key or out["need_key"]:
                                    x_encoder.force_keyframe()
                                    force_key = out["need_key"] = False
                                packets = x_encoder.encode(img)
                                nbytes, codec = 0, "h264"
                                for payload, key in packets:
                                    nbytes += len(payload)
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
                                nbytes, codec = len(jpg), "jpeg"
                        else:
                            jpg = game.render(C.X_SIZE, C.X_QUALITY)
                            out["jpeg"] = b"X" + struct.pack("!II", game.tick, seq) + jpg
                            out["ev"].set()
                            nbytes, codec = len(jpg), "jpeg"
                        log_frame(game.tick, seq, codec,
                                  (time.perf_counter() - t0) * 1000, nbytes)
                elif m["tick"] > game.tick + 1 and (not resync or time.monotonic() - need_at > 2.0):
                    resync, need_at = True, time.monotonic()
                    await send(json.dumps({"t": "need_snap"}))
    finally:
        rd.cancel()
        sd.cancel()
        await asyncio.gather(rd, sd, return_exceptions=True)
        print("Y disconnected")


async def main():
    global log_f, log_w, x_encoder
    log_f = open("log_x.csv", "w", newline="")
    log_w = csv.writer(log_f)
    log_w.writerow(["unix_time", "tick", "seq", "codec", "encode_ms", "frame_bytes"])

    if C.X_CODEC == "h264" and H264Encoder is not None:
        try:
            x_encoder = H264Encoder(C.X_SIZE, C.X_FPS, C.X_BITRATE, C.X_GOP)
            print(f"X video encoder: H.264 via {x_encoder.name} "
                  f"({C.X_SIZE[0]}x{C.X_SIZE[1]} @ {C.X_FPS} fps, "
                  f"{C.X_BITRATE} bps, GOP {C.X_GOP})")
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
