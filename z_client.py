"""END NODE Z (laptop B): samples keyboard, shows frames. NO game logic.
Does not need Pillow or the images. H.264 frames are decoded with PyAV."""
import asyncio, csv, io, json, os, struct, time
import pygame
from websockets.exceptions import ConnectionClosed
from websockets.asyncio.client import connect
from common import config as C
from game.settings import load_config, merge_config, normalize_config
from ui.config_menu import ConfigMenu
from ui.leaderboard import LeaderboardScreen
from ui.menu import Menu
from ui.overlay import GameOverMenu, PauseMenu
try:
    from common.video import H264Decoder
except ImportError:                      # PyAV not installed: JPEG only
    H264Decoder = None
from common.win import hires_timer
hires_timer()

KEYMAP = (("w", pygame.K_w), ("a", pygame.K_a), ("s", pygame.K_s), ("d", pygame.K_d), (" ", pygame.K_SPACE))


def pattern_keys(name, elapsed):
    """Deterministic input pattern for unattended test runs."""
    if name == "idle":
        return ""
    if name == "strafe":
        return "d" if int(elapsed / 2.0) % 2 == 0 else "a"
    if name == "circle":
        return ("d", "s", "a", "w")[int(elapsed / 2.0) % 4]
    if name == "figure8":
        return ("d", "dw", "w", "wa", "a", "as", "s", "sd")[int(elapsed / 1.5) % 8]
    if name == "shoot":
        keys = "d" if int(elapsed / 3.0) % 2 == 0 else "a"
        if elapsed % 0.5 < 0.15:
            keys += " "
        return keys
    return ""


async def fetch_leaderboard(top=10, timeout=4.0):
    """Ask Y for L's top rows (WS3.4); returns ``(rows, error, count)``."""
    end = time.monotonic() + timeout
    try:
        async with connect(C.Y_URI, max_size=1 << 20, compression=None,
                           ping_interval=C.PING_INTERVAL,
                           ping_timeout=C.PING_TIMEOUT) as ws:
            await ws.send(json.dumps({"t": "hello",
                                      "h264": H264Decoder is not None}))
            await ws.send(json.dumps({"t": "version"}))     # old-Y detection
            await ws.send(json.dumps({"t": "leaderboard_get", "top": top}))
            while True:
                left = end - time.monotonic()
                if left <= 0:
                    return ([], "Y did not answer in time (is Middle Y "
                                "running the current build?)", None)
                raw = await asyncio.wait_for(ws.recv(), timeout=left)
                if not isinstance(raw, (str, bytes, bytearray)):
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if msg.get("t") == "version" and not msg.get("leaderboard"):
                    return [], (f"Middle Y is an older build ({msg.get('y')}); "
                                f"restart it from the current code"), None
                if msg.get("t") == "leaderboard":
                    return (msg.get("rows") or [], msg.get("error"),
                            msg.get("count"))
    except ConnectionClosed:
        return [], ("Middle Y closed the link — it is probably an older build; "
                    "restart it from the current code"), None
    except (OSError, asyncio.TimeoutError) as exc:
        return [], f"Y unavailable ({type(exc).__name__})", None


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
    leaderboard_screen = LeaderboardScreen(screen, font)
    os.makedirs("logs", exist_ok=True)
    log_f = open(os.path.join("logs", "log_z.csv"), "w", newline="")
    log = csv.writer(log_f)
    log.writerow(["unix_time", "source", "codec", "tick", "first",
                  "e2e_ms", "decode_ms", "rtt_zy_ms"])

    test_mode = os.environ.get("FYP_TEST") == "1"
    sent, st = {}, {"e2e": 0.0, "rzy": 0.0, "want_idr": False,
                    "game_over": False, "score": 0, "deaths": 0,
                    "workload": "heavy", "pause_requested": False,
                    "return_to_menu": False, "test_mode": test_mode,
                    "test_state": "ready", "pattern": "strafe",
                    "test_t0": 0.0, "fps": 0.0, "decode": 0.0}
    seq, nframes, running = 0, 0, True
    pending_space, last_frame = False, None

    def pump_events():
        """Returns False once the window was closed."""
        nonlocal pending_space, running
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                if not st["test_mode"]:
                    st["pause_requested"] = True
            if e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE:
                if not st["test_mode"]:
                    pending_space = True    # a tap between two ticks must not be lost
        return running

    async def input_loop(ws):
        nonlocal seq, pending_space
        nxt = time.monotonic()
        ping_every = max(1, C.Z_PING_EVERY * max(1, C.Z_INPUT_HZ // C.TICK_RATE))
        while (pump_events() and not st["game_over"]
               and st["test_state"] != "finished"):
            if st["test_state"] == "paused":
                nxt = time.monotonic()
                await asyncio.sleep(1 / max(1, C.Z_INPUT_HZ))
                continue
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
            if st["test_mode"]:
                elapsed = (time.monotonic() - st["test_t0"]
                           if st["test_t0"] else 0.0)
                keys = pattern_keys(st["pattern"], elapsed)
                pending_space = False
            else:
                k = pygame.key.get_pressed()
                keys = "".join(c for c, kc in KEYMAP if k[kc])
                if pending_space and " " not in keys:
                    keys += " "
                pending_space = False
            seq += 1
            sent[seq] = time.monotonic()
            sent.pop(seq - C.Z_INPUT_HZ * 10, None)   # keep ~10 s of history
            msg = {"keys": keys, "n": seq, "e2e": st["e2e"],
                   "rzy": round(st["rzy"], 1),
                   "fps": round(st.get("fps", 0.0), 1),
                   "decode": round(st.get("decode", 0.0), 1)}
            if st.pop("want_idr", False):        # the decoder lost its reference
                msg["want_idr"] = True
            if seq % ping_every == 0:            # ~10 probes/s, independent of input rate
                msg["pts"] = time.monotonic()
            await ws.send(json.dumps(msg))
            nxt += 1 / C.Z_INPUT_HZ
            await asyncio.sleep(max(0, nxt - time.monotonic()))

    async def receiver(ws):
        nonlocal nframes, last_frame, seq, pending_space
        overlay = shadow = None
        last_src = last_codec = None
        decoder = None
        dec_src = None
        need_key = True                          # wait for an IDR before decoding P-frames
        last_tick = None
        last_seq = None
        strides = {}                             # WS3.5: declared stream stride
        fps_count, fps_t0, fps_value = 0, None, None
        async for msg in ws:
            if isinstance(msg, str):
                m = json.loads(msg)
                kind = m.get("t")
                if kind == "pong":               # Z<->Y latency probe
                    ms = (time.monotonic() - m["ts"]) * 1000
                    st["rzy"] = ms if not st["rzy"] else 0.8 * st["rzy"] + 0.2 * ms
                elif kind == "stride":
                    # WS3.5: the sender states how many ticks it skips.
                    # 0 = irregular cadence (stage chain): a tick gap is normal
                    # and must not trigger the IDR/freeze loop.
                    strides[m.get("src")] = int(m.get("n", 0))
                elif kind == "game_over":
                    st["game_over"] = True
                    st["score"] = int(m.get("score", 0))
                    st["deaths"] = int(m.get("deaths", 0))
                    print(f"game over: score={st['score']}")
                    return
                elif kind == "test":
                    cmd = m.get("cmd")
                    if cmd == "start":
                        test_config = game_config
                        if m.get("safe"):
                            # WS3.4.1: Y overlays a measurement-safe player so
                            # the match cannot end before duration_s.
                            test_config = normalize_config(
                                merge_config(game_config, m["safe"]))
                            print(f"[{time.strftime('%X')}] test-safe config: "
                                  f"hp={test_config['player']['max_hp']}, "
                                  f"obstacle_damage="
                                  f"{test_config['player']['obstacle_damage']}, "
                                  f"bot_damage="
                                  f"{test_config['player']['bot_damage']}, "
                                  f"bot_bullet_damage="
                                  f"{test_config['bot']['bullet_damage']}")
                        st["workload"] = m.get("workload", "light")
                        st["pattern"] = m.get("pattern", st["pattern"])
                        st["test_state"] = "running"
                        st["test_t0"] = time.monotonic()
                        st.update(e2e=0.0, rzy=0.0, want_idr=False,
                                  game_over=False, score=0, deaths=0,
                                  return_to_menu=False)
                        sent.clear()
                        seq = 0
                        pending_space = False
                        last_seq = None
                        last_tick = None
                        need_key = True
                        print(f"[{time.strftime('%X')}] test start: "
                              f"{st['workload']} / {st['pattern']}")
                        await ws.send(json.dumps({"t": "start", "mode": "vs_bot",
                                                  "workload": st["workload"],
                                                  "seed": int(m.get("seed", 12345)),
                                                  "config": test_config}))
                    elif cmd == "pause":
                        st["test_state"] = "paused"
                    elif cmd == "resume":
                        st["test_state"] = "running"
                    elif cmd == "pattern":
                        st["pattern"] = m.get("pattern", st["pattern"])
                    elif cmd == "stop":
                        st["test_state"] = "finished"
                        st["return_to_menu"] = True
                        print(f"[{time.strftime('%X')}] test stopped")
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
                    last_tick = None
                # The sender may stream every Nth tick (Y: 2, X: 1), and a
                # stage chain declares 0 = irregular. Only a jump larger than
                # the declared stride is a dropped frame, not a normal step.
                step = strides.get(src)
                if step is None:
                    step = C.X_STREAM_EVERY if src == "x" else C.Y_STREAM_EVERY
                jump = (last_tick is not None
                        and (tick < last_tick
                             or (step and tick > last_tick + step)))
                if jump:
                    if not need_key:
                        st["want_idr"] = True    # a frame was dropped: ask for an IDR
                    need_key = True              # do not draw until a clean reference arrives
                last_tick = tick
                if C.X_INTRA_REFRESH and src == "x":
                    # Intra-refresh has no periodic IDR. Keep decoding through
                    # a gap and let the rolling refresh repair the picture.
                    need_key = False
                if need_key and not keyframe:
                    continue
                if keyframe:
                    need_key = False
                    # With intra-refresh x264 still flags some refresh points as
                    # keyframes; resetting the decoder there loses the rolling
                    # reference and freezes half the frames. Only reset for a
                    # normal GOP stream.
                    if not (C.X_INTRA_REFRESH and src == "x"):
                        decoder.reset()
                t_dec = time.perf_counter()
                # Decode off the event loop so the 120 Hz input sampler keeps
                # running while a 720p frame is decoded.
                frames = await asyncio.to_thread(decoder.decode, payload)
                decode_ms = (time.perf_counter() - t_dec) * 1000
                if not frames:
                    continue
                pil = frames[-1]
                img = pygame.image.frombuffer(pil.tobytes(), pil.size, "RGB")
                src = src.upper()                # overlay/log use X/Y
            else:
                # JPEG: source | tick | seq | payload
                codec = "jpeg"
                tick, s = struct.unpack("!II", msg[1:9])
                t_dec = time.perf_counter()
                img = pygame.image.load(io.BytesIO(msg[9:]), "f.jpg")
                decode_ms = (time.perf_counter() - t_dec) * 1000
            first = 1 if s != last_seq else 0
            last_seq = s
            st["decode"] = decode_ms
            if img.get_size() != (C.WIN_W, C.WIN_H):
                img = pygame.transform.scale(img, (C.WIN_W, C.WIN_H))
            last_frame = img
            screen.blit(img, (0, 0))
            t0 = sent.get(s)
            if t0:
                ms = (time.monotonic() - t0) * 1000
                if first:       # only the first frame for an input is the real latency
                    st["e2e"] = ms if not st["e2e"] else 0.9 * st["e2e"] + 0.1 * ms
                log.writerow([round(time.time(), 3), src, codec, tick, first,
                              round(ms, 1), round(decode_ms, 1), round(st["rzy"], 1)])
            nframes += 1
            fps_count += 1
            now = time.monotonic()
            if fps_t0 is None:
                fps_t0 = now
            elif now - fps_t0 >= 1.0:
                fps_value = fps_count / (now - fps_t0)
                fps_count, fps_t0 = 0, now
                st["fps"] = fps_value
            if nframes % 30 == 0:
                log_f.flush()
            # the overlay only needs refreshing a few times per second
            if overlay is None or src != last_src or codec != last_codec or nframes % 12 == 0:
                col = (80, 255, 120) if src == "X" else (255, 170, 50)
                txt = (f"{'CLOUD X' if src == 'X' else 'EDGE Y'} "
                       f"({'H.264' if codec == 'h264' else 'JPEG'})"
                       f"   input->display {st['e2e']:.0f} ms   Y link {st['rzy']:.0f} ms")
                if st["test_mode"]:
                    elapsed = (time.monotonic() - st["test_t0"]
                               if st["test_t0"] else 0.0)
                    txt = (f"TEST {st['test_state'].upper():<8} "
                           f"{elapsed:5.1f}s   " + txt)
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
        if test_mode:
            # Unattended mode: no menu. Connect, advertise capabilities, then wait
            # for Y to drive test start/pause/resume/stop commands.
            while running:
                if not pump_events():
                    break
                try:
                    async with connect(C.Y_URI, max_size=4 << 20, compression=None,
                                       ping_interval=C.PING_INTERVAL,
                                       ping_timeout=C.PING_TIMEOUT) as ws:
                        print(f"test mode: connected to Y at {C.Y_URI}")
                        await ws.send(json.dumps({"t": "hello",
                                                  "h264": H264Decoder is not None}))
                        st.update(test_state="ready", test_t0=0.0,
                                  return_to_menu=False, game_over=False)
                        await session(ws)
                except (OSError, ConnectionClosed) as e:
                    print(f"Y link down ({e!r})")
                if not running:
                    break
                await asyncio.sleep(1.0)
            return
        while running:
            if pending_workload is not None:
                choice = {"action": "start", "workload": pending_workload}
                pending_workload = None
            elif auto:
                choice = {"action": "start", "workload": auto_workload}
                auto = False
            else:
                choice = menu.run(last_result, status)
            if choice and choice.get("action") == "leaderboard":
                rows, error, count = await fetch_leaderboard()
                leaderboard_screen.run(rows, error, count)
                continue
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
