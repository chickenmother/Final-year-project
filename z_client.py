"""END NODE Z (laptop B): samples keyboard, shows frames. NO game logic. Does not need Pillow or the images."""
import asyncio, csv, io, json, struct, sys, time
import pygame
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
    sent, st = {}, {"e2e": 0.0}
    log_f = open("log_z.csv", "w", newline="")
    log = csv.writer(log_f)
    log.writerow(["unix_time", "source", "tick", "e2e_ms"])
    seq, pending_space, nframes = 0, False, 0

    async with connect(C.Y_URI, max_size=None, compression=None, ping_interval=None) as ws:
        async def input_loop():
            nonlocal seq, pending_space
            nxt = time.monotonic()
            while True:
                for e in pygame.event.get():
                    if e.type == pygame.QUIT:
                        sys.exit()
                    if e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE:
                        pending_space = True
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

        async def receiver():
            nonlocal nframes
            async for msg in ws:
                src = chr(msg[0])
                tick, s = struct.unpack("!II", msg[1:9])
                img = pygame.image.load(io.BytesIO(msg[9:]), "f.jpg")
                screen.blit(pygame.transform.scale(img, (C.WIN_W, C.WIN_H)), (0, 0))
                t0 = sent.get(s)
                if t0:
                    ms = (time.monotonic() - t0) * 1000
                    st["e2e"] = ms if not st["e2e"] else 0.9 * st["e2e"] + 0.1 * ms
                    log.writerow([round(time.time(), 3), src, tick, round(ms, 1)])
                nframes += 1
                if nframes % 30 == 0:
                    log_f.flush()
                col = (80, 255, 120) if src == "X" else (255, 170, 50)
                txt = f"{'CLOUD X (high quality)' if src == 'X' else 'EDGE Y (fallback)'}   input->display {st['e2e']:.0f} ms"
                screen.blit(font.render(txt, True, (0, 0, 0)), (11, 11))
                screen.blit(font.render(txt, True, col), (10, 10))
                pygame.display.flip()

        try:
            await asyncio.gather(input_loop(), receiver())
        finally:
            log_f.close()

asyncio.run(main())
