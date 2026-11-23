"""Local menu for End Node Z.

The menu is deliberately local: it must render immediately even when X/Y are
unreachable. Leaderboard/multiplayer are visible but disabled until later
milestones.
"""
import pygame

from game.settings import normalize_config, profiles_from_config


class Menu:
    def __init__(self, screen, font=None, config=None):
        self.screen = screen
        w, h = screen.get_size()
        self.sx, self.sy = w / 960.0, h / 540.0
        self.font = pygame.font.SysFont("consolas", max(18, int(20 * self.sy)))
        self.big = pygame.font.SysFont("consolas", max(32, int(44 * self.sy)), bold=True)
        self.small = pygame.font.SysFont("consolas", max(14, int(16 * self.sy)))
        self.clock = pygame.time.Clock()
        self.config = normalize_config(config)
        self.profiles = profiles_from_config(self.config)
        self.workloads = tuple(self.profiles)
        self.workload = self.config["default_workload"]
        self.quit = False

        bw, bh = int(340 * self.sx), int(42 * self.sy)
        x = w // 2 - bw // 2
        step = int(46 * self.sy)
        top = int(208 * self.sy)
        self.buttons = {
            "vs_bot": pygame.Rect(x, top, bw, bh),
            "leaderboard": pygame.Rect(x, top + step, bw, bh),
            "multiplayer": pygame.Rect(x, top + step * 2, bw, bh),
            "config": pygame.Rect(x, top + step * 3, bw, bh),
            "exit": pygame.Rect(x, top + step * 4, bw, bh),
        }
        cw, ch = int(130 * self.sx), int(30 * self.sy)
        self.chips = {
            name: pygame.Rect(w // 2 - int(210 * self.sx) + i * int(145 * self.sx),
                              int(478 * self.sy), cw, ch)
            for i, name in enumerate(self.workloads)
        }

    def _draw_button(self, rect, label, enabled=True, hover=False):
        if not enabled:
            bg, fg = (38, 42, 52), (110, 115, 125)
        else:
            bg, fg = ((60, 110, 90) if hover else (42, 58, 76)), (230, 240, 250)
        pygame.draw.rect(self.screen, bg, rect, border_radius=8)
        pygame.draw.rect(self.screen, (90, 120, 150), rect, 2, border_radius=8)
        text = self.font.render(label, True, fg)
        self.screen.blit(text, text.get_rect(center=rect.center))

    def _draw(self, last_result, status):
        self.screen.fill((10, 14, 24))
        w, h = self.screen.get_size()
        title = self.big.render("CLOUD / EDGE ARENA", True, (220, 240, 255))
        self.screen.blit(title, title.get_rect(center=(w // 2, int(88 * self.sy))))
        sub = self.small.render(
            "3-tier task-placement prototype   |   menu is local on Z",
            True, (140, 180, 210))
        self.screen.blit(sub, sub.get_rect(center=(w // 2, int(130 * self.sy))))

        mouse = pygame.mouse.get_pos()
        self._draw_button(self.buttons["vs_bot"], "VS BOT  (start)",
                          hover=self.buttons["vs_bot"].collidepoint(mouse))
        self._draw_button(self.buttons["leaderboard"], "LEADERBOARD  (later)", False)
        self._draw_button(self.buttons["multiplayer"], "MULTIPLAYER  (later)", False)
        self._draw_button(self.buttons["config"], "GAME CONFIG  (C)",
                          hover=self.buttons["config"].collidepoint(mouse))
        self._draw_button(self.buttons["exit"], "EXIT",
                          hover=self.buttons["exit"].collidepoint(mouse))

        selected = self.small.render(
            f"selected: {self.workload} ({self.profiles[self.workload].bots} bots)",
            True, (200, 220, 235))
        self.screen.blit(selected, (w // 2 - int(340 * self.sx), int(444 * self.sy)))
        label = self.small.render("workload (1/2/3):", True, (180, 200, 220))
        self.screen.blit(label, (w // 2 - int(340 * self.sx), int(460 * self.sy)))
        for name, rect in self.chips.items():
            active = name == self.workload
            bg = (70, 130, 100) if active else (40, 50, 64)
            pygame.draw.rect(self.screen, bg, rect, border_radius=6)
            pygame.draw.rect(self.screen, (100, 150, 180), rect, 2, border_radius=6)
            label = f"{name.upper()} ({self.profiles[name].bots} bots)"
            text = self.small.render(label, True, (240, 245, 250))
            self.screen.blit(text, text.get_rect(center=rect.center))

        if last_result is not None:
            msg = self.small.render(f"last score: {last_result}", True, (150, 230, 170))
            self.screen.blit(msg, msg.get_rect(center=(w // 2, int(165 * self.sy))))
        if status:
            msg = self.small.render(status[:90], True, (255, 150, 130))
            self.screen.blit(msg, msg.get_rect(center=(w // 2, int(185 * self.sy))))

        hint = self.small.render(
            "Enter/Space start   C config   Esc exit   WASD + Space in game",
            True, (110, 130, 150))
        self.screen.blit(hint, hint.get_rect(center=(w // 2, h - int(16 * self.sy))))
        pygame.display.flip()

    def run(self, last_result=None, status=None):
        """Block until Start or Exit. Returns an action dict or None."""
        while not self.quit:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.quit = True
                    return None
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self.quit = True
                        return None
                    if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                        return {"action": "start", "workload": self.workload,
                                "config": self.config}
                    if event.key == pygame.K_c:
                        return {"action": "config"}
                    if event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                        index = event.key - pygame.K_1
                        if index < len(self.workloads):
                            self.workload = self.workloads[index]
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for name, rect in self.buttons.items():
                        if not rect.collidepoint(event.pos):
                            continue
                        if name == "exit":
                            self.quit = True
                            return None
                        if name == "config":
                            return {"action": "config"}
                        if name == "vs_bot":
                            return {"action": "start", "workload": self.workload,
                                    "config": self.config}
                    for name, rect in self.chips.items():
                        if rect.collidepoint(event.pos):
                            self.workload = name
            self._draw(last_result, status)
            self.clock.tick(60)
        return None
