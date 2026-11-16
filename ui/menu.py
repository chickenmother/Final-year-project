"""Local menu for End Node Z.

The menu is deliberately local: it must render immediately even when X/Y are
unreachable. Leaderboard/multiplayer are visible but disabled until later
milestones.
"""
import pygame

WORKLOADS = ("light", "medium", "heavy")


class Menu:
    def __init__(self, screen, font):
        self.screen = screen
        self.font = font
        self.big = pygame.font.SysFont("consolas", 44, bold=True)
        self.small = pygame.font.SysFont("consolas", 16)
        self.clock = pygame.time.Clock()
        self.workload = "heavy"
        self.quit = False

        w, h = screen.get_size()
        self.buttons = {
            "vs_bot": pygame.Rect(w // 2 - 170, 210, 340, 52),
            "leaderboard": pygame.Rect(w // 2 - 170, 274, 340, 52),
            "multiplayer": pygame.Rect(w // 2 - 170, 338, 340, 52),
            "exit": pygame.Rect(w // 2 - 170, 402, 340, 52),
        }
        self.chips = {
            name: pygame.Rect(w // 2 - 210 + i * 145, 480, 130, 34)
            for i, name in enumerate(WORKLOADS)
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
        self.screen.blit(title, title.get_rect(center=(w // 2, 88)))
        sub = self.small.render(
            "3-tier task-placement prototype   |   menu is local on Z",
            True, (140, 180, 210))
        self.screen.blit(sub, sub.get_rect(center=(w // 2, 130)))

        mouse = pygame.mouse.get_pos()
        self._draw_button(self.buttons["vs_bot"], "VS BOT  (start)",
                          hover=self.buttons["vs_bot"].collidepoint(mouse))
        self._draw_button(self.buttons["leaderboard"], "LEADERBOARD  (later)", False)
        self._draw_button(self.buttons["multiplayer"], "MULTIPLAYER  (later)", False)
        self._draw_button(self.buttons["exit"], "EXIT",
                          hover=self.buttons["exit"].collidepoint(mouse))

        label = self.small.render("workload (1/2/3):", True, (180, 200, 220))
        self.screen.blit(label, (w // 2 - 340, 486))
        for name, rect in self.chips.items():
            active = name == self.workload
            bg = (70, 130, 100) if active else (40, 50, 64)
            pygame.draw.rect(self.screen, bg, rect, border_radius=6)
            pygame.draw.rect(self.screen, (100, 150, 180), rect, 2, border_radius=6)
            text = self.small.render(name.upper(), True, (240, 245, 250))
            self.screen.blit(text, text.get_rect(center=rect.center))

        if last_result is not None:
            msg = self.small.render(f"last score: {last_result}", True, (150, 230, 170))
            self.screen.blit(msg, msg.get_rect(center=(w // 2, 165)))
        if status:
            msg = self.small.render(status[:90], True, (255, 150, 130))
            self.screen.blit(msg, msg.get_rect(center=(w // 2, 185)))

        hint = self.small.render(
            "Enter/Space start   Esc exit   WASD + Space in game",
            True, (110, 130, 150))
        self.screen.blit(hint, hint.get_rect(center=(w // 2, h - 16)))
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
                        return {"action": "start", "workload": self.workload}
                    if event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                        self.workload = WORKLOADS[event.key - pygame.K_1]
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for name, rect in self.buttons.items():
                        if not rect.collidepoint(event.pos):
                            continue
                        if name == "exit":
                            self.quit = True
                            return None
                        if name == "vs_bot":
                            return {"action": "start", "workload": self.workload}
                    for name, rect in self.chips.items():
                        if rect.collidepoint(event.pos):
                            self.workload = name
            self._draw(last_result, status)
            self.clock.tick(60)
        return None
