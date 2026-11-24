"""U: the leaderboard view on End Z (WS3.4).

The rows come from L (SQLite on Cloud X) through Y, and Z only renders them —
no game state is read here, so the screen is pure UI.
"""
import time

import pygame


def _fmt_time(created):
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(float(created)))
    except (TypeError, ValueError, OSError):
        return "-"


class LeaderboardScreen:
    def __init__(self, screen, font=None):
        self.screen = screen
        w, h = screen.get_size()
        self.sx, self.sy = w / 960.0, h / 540.0
        self.font = pygame.font.SysFont("consolas", max(16, int(18 * self.sy)))
        self.big = pygame.font.SysFont("consolas", max(26, int(34 * self.sy)),
                                       bold=True)
        self.small = pygame.font.SysFont("consolas", max(13, int(15 * self.sy)))
        self.clock = pygame.time.Clock()

    def _row(self, y, cells, widths, colour=(225, 235, 245), bold=False):
        x = int(70 * self.sx)
        font = self.font if not bold else self.font
        for text, width in zip(cells, widths):
            surface = font.render(str(text), True, colour)
            self.screen.blit(surface, (x, y))
            x += int(width * self.sx)

    def draw(self, rows, error=None, count=None):
        self.screen.fill((10, 14, 24))
        w, h = self.screen.get_size()
        title = self.big.render("LEADERBOARD", True, (220, 240, 255))
        self.screen.blit(title, title.get_rect(center=(w // 2, int(60 * self.sy))))
        sub = self.small.render(
            "L: SQLite on Cloud X   |   U: this view, local on End Z"
            + (f"   |   {count} score(s)" if count else ""),
            True, (140, 180, 210))
        self.screen.blit(sub, sub.get_rect(center=(w // 2, int(96 * self.sy))))

        widths = (70, 230, 120, 120, 150)
        header_y = int(140 * self.sy)
        self._row(header_y, ("#", "NAME", "SCORE", "DEATHS", "WHEN"),
                  widths, (150, 190, 220), bold=True)
        pygame.draw.line(self.screen, (60, 80, 100),
                         (int(70 * self.sx), header_y + int(24 * self.sy)),
                         (int(830 * self.sx), header_y + int(24 * self.sy)), 1)

        y = header_y + int(34 * self.sy)
        if error:
            msg = self.small.render(f"unavailable: {error}", True, (255, 150, 130))
            self.screen.blit(msg, (int(70 * self.sx), y))
        elif not rows:
            msg = self.small.render("no scores yet — finish a match to appear here",
                                    True, (180, 200, 215))
            self.screen.blit(msg, (int(70 * self.sx), y))
        else:
            for index, row in enumerate(rows, 1):
                if y > h - int(70 * self.sy):
                    break
                self._row(y, (index, row.get("name", "-"),
                              row.get("score", 0), row.get("deaths", 0),
                              _fmt_time(row.get("created"))), widths)
                y += int(26 * self.sy)

        hint = self.small.render("Esc / Enter / click to return",
                                 True, (110, 130, 150))
        self.screen.blit(hint, hint.get_rect(center=(w // 2,
                                                     h - int(24 * self.sy))))
        pygame.display.flip()

    def run(self, rows, error=None, count=None):
        """Block until the player leaves; returns nothing."""
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return
                if event.type == pygame.KEYDOWN and event.key in (
                        pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER,
                        pygame.K_SPACE, pygame.K_l):
                    return
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    return
            self.draw(rows, error, count)
            self.clock.tick(30)
