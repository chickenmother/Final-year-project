"""END NODE Z (laptop B): samples keyboard, shows frames. NO game logic.
Does not need Pillow or the images. H.264 frames are decoded with PyAV."""
import asyncio, csv, io, json, os, struct, time
import pygame
from websockets.exceptions import ConnectionClosed
from websockets.asyncio.client import connect
from common import config as C
from game.settings import load_config, normalize_config
from ui.config_menu import ConfigMenu
from ui.menu import Menu
from ui.overlay import GameOverMenu, PauseMenu
try:
    from common.video import H264Decoder
except ImportError:                      # PyAV not installed: JPEG only
    H264Decoder = None
from common.win import hires_timer
hires_timer()

KEYMAP = (("w", pygame.K_w), ("a", pygame.K_a), ("s", pygame.K_s), ("d", pygame.K_d), (" ", pygame.K_SPACE))


async def main():
    pygame.init()
    screen = pygame.display.set_mode((C.WIN_W, C.WIN_H))
    pygame.display.set_caption("Z - end node (WASD + SPACE)")
    font = pygame.font.SysFont("consolas", max(18, int(C.WIN_H / 36)))
    game_config = load_config()
    menu = Menu(screen, font, game_config)
    config_menu = ConfigMenu(screen, font)
    pause_menu = PauseMenu(screen, font)
    gameover_menu = GameOverMenu(screen, font)
    os.makedirs("logs", exist_ok=True)
    log_f = open(os.path.join("logs", "log_z.csv"), "w", newline="")
    log = csv.writer(log_f)
    log.writerow(["unix_time", "source", "codec", "tick", "e2e_ms", "rtt_zy_ms"])

    sent, st = {}, {"e2e": 0.0, "rzy": 0.0, "want_idr": False,
                    "game_over": False, "score": 0, "deaths": 0,
                    "workload": "heavy", "pause_requested": False,
                    "return_to_menu": False}
    seq, nframes, running = 0, 0, True
    pending_space, last_frame = False, None

    def pump_events():
        """Returns False once the window was closed."""
        nonlocal pending_space, running
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                st["pause_requested"] = True
            if e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE:
                pending_space = True        # a tap between two ticks must not be lost
        return running

    async def input_loop(ws):
        nonlocal seq, pending_space
        nxt = time.monotonic()
        while pump_events() and not st["game_over"]:
            if st.pop("pause_requested", False):
                await ws.send(json.dumps({"t": "pause"}))
                choice = pause_menu.run(last_frame, st["score"])
                if choice == "retry":
                    sent.clear()
                    seq = 0
                    pending_space = False
                    st.update(e2e=0.0, rzy=0.0, want_idr=False,
                              game_over=False, score=0, deaths=0)
                    await ws.send(json.dumps({"t": "start", "mode": "vs_bot",
                                              "workload": st["workload"], "seed": 12345,
                                              "config": game_config}))
                    continue
                if choice in ("menu", "exit") or choice is None:
                    if choice == "exit":
                        running = False
                    st["return_to_menu"] = True
                    return
                await ws.send(json.dumps({"t": "resume"}))
                continue
            k = pygame.key.get_pressed()
            keys = "".join(c for c, kc in KEYMAP if k[kc])
            if pending_space and " " not in keys:
                keys += " "
            pending_space = False
            seq += 1
            sent[seq] = time.monotonic()
            sent.pop(seq - 600, None)
            msg = {"keys": keys, "n": seq, "e2e": st["e2e"], "rzy": round(st["rzy"], 1)}
            if st.pop("want_idr", False):        # the decoder lost its reference
                msg["want_idr"] = True
            if seq % C.Z_PING_EVERY == 0:        # probe the Z<->Y hop a few times per second
                msg["pts"] = time.monotonic()
            await ws.send(json.dumps(msg))
            nxt += 1 / C.TICK_RATE
            await asyncio.sleep(max(0, nxt - time.monotonic()))

    async def receiver(ws):
        nonlocal nframes, last_frame
        overlay = shadow = None
        last_src = last_codec = None
        decoder = None
        dec_src = None
        need_key = True                          # wait for an IDR before decoding P-frames
        last_tick = None
        fps_count, fps_t0, fps_value = 0, None, None
        async for msg in ws:
            if isinstance(msg, str):
                m = json.loads(msg)
                kind = m.get("t")
                if kind == "pong":               # Z<->Y latency probe
                    ms = (time.monotonic() - m["ts"]) * 1000
                    st["rzy"] = ms if not st["rzy"] else 0.8 * st["rzy"] + 0.2 * ms
                elif kind == "game_over":
                    st["game_over"] = True
                    st["score"] = int(m.get("score", 0))
                    st["deaths"] = int(m.get("deaths", 0))
                    print(f"game over: score={st['score']}")
                    return
                continue
            src = chr(msg[0])
            if src in ("x", "y"):
                # H.264: source | keyframe flag | tick | seq | payload
                codec = "h264"
                if H264Decoder is None:
                    continue
                keyframe = bool(msg[1])
                tick, s = struct.unpack("!II", msg[2:10])
                payload = msg[10:]
                if decoder is None or dec_src != src:
                    decoder, dec_src, need_key = H264Decoder(), src, True
                if last_tick is not None and tick > last_tick + 1:
                    if not need_key:
                        st["want_idr"] = True    # a frame was dropped: ask for an IDR
                    need_key = True              # do not draw until a clean reference arrives
                last_tick = tick
                if need_key and not keyframe:
                    continue
                if keyframe:
                    need_key = False
                    decoder.reset()
                frames = decoder.decode(payload)
                if not frames:
                    continue
                pil = frames[-1]
                img = pygame.image.frombuffer(pil.tobytes(), pil.size, "RGB")
                src = src.upper()                # overlay/log use X/Y
            else:
                # JPEG: source | tick | seq | payload
                codec = "jpeg"
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
                log.writerow([round(time.time(), 3), src, codec, tick, round(ms, 1),
                              round(st["rzy"], 1)])
            nframes += 1
            fps_count += 1
            now = time.monotonic()
            if fps_t0 is None:
                fps_t0 = now
            elif now - fps_t0 >= 1.0:
                fps_value = fps_count / (now - fps_t0)
                fps_count, fps_t0 = 0, now
            if nframes % 30 == 0:
                log_f.flush()
            # the overlay only needs refreshing a few times per second
            if overlay is None or src != last_src or codec != last_codec or nframes % 12 == 0:
                col = (80, 255, 120) if src == "X" else (255, 170, 50)
                txt = (f"{'CLOUD X' if src == 'X' else 'EDGE Y'} "
                       f"({'H.264' if codec == 'h264' else 'JPEG'})"
                       f"   input->display {st['e2e']:.0f} ms   Y link {st['rzy']:.0f} ms")
                shadow = font.render(txt, True, (0, 0, 0))
                overlay = font.render(txt, True, col)
                last_src, last_codec = src, codec
            screen.blit(shadow, (11, 11))
            screen.blit(overlay, (10, 10))
            fps_label = "-- FPS" if fps_value is None else f"{fps_value:.0f} FPS"
            fps_text = font.render(fps_label, True, col)
            fps_shadow = font.render(fps_label, True, (0, 0, 0))
            fps_x = screen.get_width() - fps_text.get_width() - 11
            screen.blit(fps_shadow, (fps_x + 1, 11))
            screen.blit(fps_text, (fps_x, 10))
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

    last_result, status = None, None
    auto = os.environ.get("FYP_SKIP_MENU") == "1"
    auto_workload = os.environ.get("FYP_MENU_WORKLOAD", game_config["default_workload"])
    pending_workload = None
    try:
        while running:
            if pending_workload is not None:
                choice = {"action": "start", "workload": pending_workload}
                pending_workload = None
            elif auto:
                choice = {"action": "start", "workload": auto_workload}
                auto = False
            else:
                choice = menu.run(last_result, status)
            if choice and choice.get("action") == "config":
                updated = config_menu.run(game_config)
                if config_menu.quit:
                    break
                game_config = normalize_config(updated)
                menu = Menu(screen, font, game_config)
                status = None
                continue
            if not choice or choice.get("action") != "start":
                break

            game_config = normalize_config(choice.get("config") or game_config)
            workload = choice.get("workload", game_config["default_workload"])
            st.update(e2e=0.0, rzy=0.0, want_idr=False, game_over=False,
                      score=0, deaths=0, workload=workload,
                      pause_requested=False, return_to_menu=False)
            sent.clear()
            pending_space = False
            status = None
            try:
                async with connect(C.Y_URI, max_size=4 << 20, compression=None,
                                   ping_interval=C.PING_INTERVAL, ping_timeout=C.PING_TIMEOUT) as ws:
                    print(f"connected to Y at {C.Y_URI}")
                    await ws.send(json.dumps({"t": "hello", "h264": H264Decoder is not None}))
                    await ws.send(json.dumps({"t": "start", "mode": "vs_bot",
                                              "workload": workload, "seed": 12345,
                                              "config": game_config}))
                    await session(ws)
            except (OSError, ConnectionClosed) as e:
                print(f"Y link down ({e!r})")
                status = f"Y link down: {e!r}"
            else:
                if st.get("return_to_menu"):
                    status = "returned to menu"
                elif st["game_over"]:
                    last_result = st["score"]
                    action = gameover_menu.run(st["score"], workload, st["deaths"])
                    if action == "retry":
                        pending_workload = workload
                    elif action == "exit":
                        break
                    else:
                        status = f"game over - score {last_result}"
                elif running:
                    status = "session ended"
    finally:
        log_f.close()
        pygame.quit()


try:
    asyncio.run(main())
except KeyboardInterrupt:
    pass
