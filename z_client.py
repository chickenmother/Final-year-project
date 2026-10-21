"""END NODE Z (laptop B): samples keyboard, shows frames. NO game logic.
Does not need Pillow or the images."""
import asyncio, csv, io, json, struct, time
import pygame
from websockets.exceptions import ConnectionClosed
from websockets.asyncio.client import connect
from common import config as C
from common.win import hires_timer
hires_timer()

KEYMAP = (("w", pygame.K_w), ("a", pygame.K_a), ("s", pygame.K_s), ("d", pygame.K_d), (" ", pygame.K_SPACE))


async def main():
    pygame.init()
    screen = pygame.display.set_mode((C.WIN_W, C.WIN_H))
    pygame.display.set_caption("Z - end node (WASD + SPACE)")
    font = pygame.font.SysFont("consolas", 20)
    log_f = open("log_z.csv", "w", newline="")
    log = csv.writer(log_f)
    log.writerow(["unix_time", "source", "tick", "e2e_ms"])

    sent, st = {}, {"e2e": 0.0}
    seq, nframes, running = 0, 0, True
    pending_space, last_frame = False, None

    def pump_events():
        """Returns False once the window was closed."""
        nonlocal pending_space, running
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            if e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE:
                pending_space = True        # a tap between two ticks must not be lost
        return running

    async def input_loop(ws):
        nonlocal seq, pending_space
        nxt = time.monotonic()
        while pump_events():
            k = pygame.key.get_pressed()
            keys = "".join(c for c, kc in KEYMAP if k[kc])
            if pending_space and " " not in keys:
                keys += " "
            pending_space = False
            seq += 1
            sent[seq] = time.monotonic()
            sent.pop(seq - 600, None)
            await ws.send(json.dumps({"keys": keys, "n": seq, "e2e": st["e2e"]}))
            nxt += 1 / C.TICK_RATE
            await asyncio.sleep(max(0, nxt - time.monotonic()))

    async def receiver(ws):
        nonlocal nframes, last_frame
        overlay = shadow = None
        last_src = None
        async for msg in ws:
            src = chr(msg[0])
            tick, s = struct.unpack("!II", msg[1:9])
            img = pygame.image.load(io.BytesIO(msg[9:]), "f.jpg")
            if img.get_size() != (C.WIN_W, C.WIN_H):
                img = pygame.transform.scale(img, (C.WIN_W, C.WIN_H))
            last_frame = img
            screen.blit(img, (0, 0))
            t0 = sent.get(s)
            if t0:
                ms = (time.monotonic() - t0) * 1000
                st["e2e"] = ms if not st["e2e"] else 0.9 * st["e2e"] + 0.1 * ms
                log.writerow([round(time.time(), 3), src, tick, round(ms, 1)])
            nframes += 1
            if nframes % 30 == 0:
                log_f.flush()
            # the overlay only needs refreshing a few times per second
            if overlay is None or src != last_src or nframes % 12 == 0:
                col = (80, 255, 120) if src == "X" else (255, 170, 50)
                txt = (f"{'CLOUD X (high quality)' if src == 'X' else 'EDGE Y (fallback)'}"
                       f"   input->display {st['e2e']:.0f} ms")
                shadow = font.render(txt, True, (0, 0, 0))
                overlay = font.render(txt, True, col)
                last_src = src
            screen.blit(shadow, (11, 11))
            screen.blit(overlay, (10, 10))
            pygame.display.flip()

    async def idle(text):
        """Keep the window alive (and say why) while Y is unreachable."""
        while running:
            pump_events()
            if last_frame is not None:
                screen.blit(last_frame, (0, 0))
            screen.blit(font.render(text, True, (255, 80, 80)), (10, 10))
            pygame.display.flip()
            await asyncio.sleep(0.1)

    async def session(ws):
        tasks = [asyncio.create_task(input_loop(ws)), asyncio.create_task(receiver(ws))]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                t.result()                    # re-raise a real error; a clean QUIT just returns
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    try:
        while running:
            try:
                async with connect(C.Y_URI, max_size=4 << 20, compression=None,
                                   ping_interval=C.PING_INTERVAL, ping_timeout=C.PING_TIMEOUT) as ws:
                    print(f"connected to Y at {C.Y_URI}")
                    sent.clear()
                    await session(ws)
            except (OSError, ConnectionClosed) as e:
                print(f"Y link down ({e!r})")
            if running:
                await idle("reconnecting to Y ...")
    finally:
        log_f.close()
        pygame.quit()


try:
    asyncio.run(main())
except KeyboardInterrupt:
    pass
