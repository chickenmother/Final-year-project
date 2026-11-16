"""Pause and game-over overlays for End Node Z."""
import pygame


class _Overlay:
    def __init__(self, screen, font):
        self.screen = screen
        self.font = font
        self.big = pygame.font.SysFont("consolas", 40, bold=True)
        self.small = pygame.font.SysFont("consolas", 16)
        self.clock = pygame.time.Clock()

    def _button(self, rect, label, mouse, primary=False):
        hover = rect.collidepoint(mouse)
        bg = (60, 120, 90) if (primary and hover) else (
            (50, 95, 75) if primary else ((62, 76, 94) if hover else (40, 50, 64)))
        pygame.draw.rect(self.screen, bg, rect, border_radius=8)
        pygame.draw.rect(self.screen, (100, 150, 180), rect, 2, border_radius=8)
        text = self.font.render(label, True, (235, 242, 250))
        self.screen.blit(text, text.get_rect(center=rect.center))

    def _shade(self, frame):
        w, h = self.screen.get_size()
        if frame is not None:
            self.screen.blit(frame, (0, 0))
        shade = pygame.Surface((w, h), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 185))
        self.screen.blit(shade, (0, 0))


class PauseMenu(_Overlay):
    def run(self, last_frame=None, score=0):
        w, h = self.screen.get_size()
        buttons = {
            "resume": pygame.Rect(w // 2 - 170, 250, 340, 52),
            "retry": pygame.Rect(w // 2 - 170, 314, 340, 52),
            "menu": pygame.Rect(w // 2 - 170, 378, 340, 52),
        }
        while True:
            mouse = pygame.mouse.get_pos()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return "exit"
                if event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_ESCAPE, pygame.K_r):
                        return "resume"
                    if event.key == pygame.K_t:
                        return "retry"
                    if event.key == pygame.K_m:
                        return "menu"
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for name, rect in buttons.items():
                        if rect.collidepoint(event.pos):
                            return name
            self._shade(last_frame)
            title = self.big.render("PAUSED", True, (220, 240, 255))
            self.screen.blit(title, title.get_rect(center=(w // 2, 150)))
            sub = self.small.render(f"score: {score}", True, (170, 200, 225))
            self.screen.blit(sub, sub.get_rect(center=(w // 2, 205)))
            self._button(buttons["resume"], "RESUME  (Esc/R)", mouse, True)
            self._button(buttons["retry"], "RETRY  (T)", mouse)
            self._button(buttons["menu"], "MAIN MENU  (M)", mouse)
            pygame.display.flip()
            self.clock.tick(60)


class GameOverMenu(_Overlay):
    def run(self, score=0, workload="heavy", deaths=0):
        w, h = self.screen.get_size()
        buttons = {
            "retry": pygame.Rect(w // 2 - 170, 290, 340, 52),
            "menu": pygame.Rect(w // 2 - 170, 354, 340, 52),
            "exit": pygame.Rect(w // 2 - 170, 418, 340, 52),
        }
        while True:
            mouse = pygame.mouse.get_pos()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return "exit"
                if event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_r, pygame.K_RETURN, pygame.K_KP_ENTER):
                        return "retry"
                    if event.key == pygame.K_m:
                        return "menu"
                    if event.key == pygame.K_ESCAPE:
                        return "menu"
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for name, rect in buttons.items():
                        if rect.collidepoint(event.pos):
                            return name
            self.screen.fill((14, 18, 30))
            title = self.big.render("GAME OVER", True, (255, 190, 150))
            self.screen.blit(title, title.get_rect(center=(w // 2, 150)))
            sub = self.small.render(
                f"score: {score}   deaths: {deaths}   workload: {workload}",
                True, (180, 205, 225))
            self.screen.blit(sub, sub.get_rect(center=(w // 2, 215)))
            self._button(buttons["retry"], "RETRY  (R/Enter)", mouse, True)
            self._button(buttons["menu"], "MAIN MENU  (M/Esc)", mouse)
            self._button(buttons["exit"], "EXIT", mouse)
            pygame.display.flip()
            self.clock.tick(60)
