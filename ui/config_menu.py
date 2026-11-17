"""Visual editor for ``game_config.json`` on End Node Z."""
import pygame

from game.settings import (
    CONFIG_PATH,
    adjust_value,
    all_fields,
    format_value,
    get_value,
    load_config,
    normalize_config,
    save_config,
)


class ConfigMenu:
    """Keyboard/mouse settings screen; changes are saved immediately."""

    def __init__(self, screen, font=None):
        self.screen = screen
        w, h = screen.get_size()
        self.sx, self.sy = w / 960.0, h / 540.0
        self.font = pygame.font.SysFont("consolas", max(16, int(18 * self.sy)))
        self.small = pygame.font.SysFont("consolas", max(13, int(15 * self.sy)))
        self.big = pygame.font.SysFont("consolas", max(28, int(36 * self.sy)), bold=True)
        self.clock = pygame.time.Clock()
        self.selected = 0
        self.scroll = 0
        self.profile = "medium"
        self.status = ""
        self.quit = False

    def _rows(self):
        return all_fields(self.profile)

    def _visible_count(self):
        top = int(168 * self.sy)
        bottom = self.screen.get_height() - int(48 * self.sy)
        return max(1, (bottom - top) // int(26 * self.sy))

    def _ensure_visible(self):
        visible = self._visible_count()
        if self.selected < self.scroll:
            self.scroll = self.selected
        elif self.selected >= self.scroll + visible:
            self.scroll = self.selected - visible + 1

    def _save(self, cfg):
        try:
            cfg = save_config(cfg)
            self.status = f"saved {CONFIG_PATH.name}"
        except Exception as exc:                       # keep the editor usable on disk errors
            self.status = f"save failed: {exc}"
        return cfg

    def _tab_rects(self, cfg):
        tab_w = int(130 * self.sx)
        tab_h = int(27 * self.sy)
        x = int(40 * self.sx)
        y = int(108 * self.sy)
        rects = []
        for name in cfg["profiles"]:
            rects.append((name, pygame.Rect(x, y, tab_w, tab_h)))
            x += tab_w + int(8 * self.sx)
        return rects

    def _draw_tabs(self, cfg):
        for name, rect in self._tab_rects(cfg):
            active = name == self.profile
            bg = (64, 125, 94) if active else (35, 46, 60)
            pygame.draw.rect(self.screen, bg, rect, border_radius=5)
            pygame.draw.rect(self.screen, (95, 145, 175), rect, 1, border_radius=5)
            text = self.small.render(name.upper(), True, (235, 245, 250))
            self.screen.blit(text, text.get_rect(center=rect.center))

    def _draw(self, cfg):
        self.screen.fill((8, 12, 20))
        w, h = self.screen.get_size()
        title = self.big.render("GAME CONFIG", True, (220, 240, 255))
        self.screen.blit(title, (int(38 * self.sx), int(20 * self.sy)))
        path = self.small.render(str(CONFIG_PATH), True, (135, 170, 195))
        self.screen.blit(path, (int(40 * self.sx), int(84 * self.sy)))
        self._draw_tabs(cfg)

        header_y = int(143 * self.sy)
        pygame.draw.line(self.screen, (60, 85, 110),
                         (int(40 * self.sx), header_y),
                         (w - int(40 * self.sx), header_y), 1)
        label = self.small.render("VARIABLE", True, (145, 180, 205))
        value = self.small.render("VALUE", True, (145, 180, 205))
        self.screen.blit(label, (int(48 * self.sx), header_y - int(20 * self.sy)))
        self.screen.blit(value, (w - int(210 * self.sx), header_y - int(20 * self.sy)))

        rows = self._rows()
        top = int(168 * self.sy)
        row_h = int(26 * self.sy)
        visible = self._visible_count()
        self.scroll = max(0, min(self.scroll, max(0, len(rows) - visible)))
        self._ensure_visible()
        end = min(len(rows), self.scroll + visible)
        for index in range(self.scroll, end):
            spec = rows[index]
            y = top + (index - self.scroll) * row_h
            selected = index == self.selected
            if selected:
                pygame.draw.rect(self.screen, (38, 67, 86),
                                 (int(38 * self.sx), y - 2,
                                  w - int(76 * self.sx), row_h),
                                 border_radius=4)
            text_color = (245, 250, 255) if selected else (205, 220, 235)
            section_color = (145, 205, 180) if selected else (100, 155, 145)
            section = self.small.render(spec.section[:14], True, section_color)
            self.screen.blit(section, (int(48 * self.sx), y))
            name = self.small.render(spec.label, True, text_color)
            self.screen.blit(name, (int(178 * self.sx), y))
            number = format_value(get_value(cfg, spec.path), spec)
            value_surface = self.small.render(number, True, text_color)
            value_rect = value_surface.get_rect()
            value_rect.right = w - int(58 * self.sx)
            value_rect.y = y
            self.screen.blit(value_surface, value_rect)
            if selected:
                marker = self.small.render("< >", True, (255, 205, 120))
                self.screen.blit(marker, (w - int(42 * self.sx), y))

        footer_y = h - int(42 * self.sy)
        pygame.draw.line(self.screen, (60, 85, 110),
                         (int(40 * self.sx), footer_y - int(8 * self.sy)),
                         (w - int(40 * self.sx), footer_y - int(8 * self.sy)), 1)
        hints = ("UP/DOWN select   LEFT/RIGHT change (Shift x5)   1/2/3 profile   "
                 "S save   R reload   D default profile   ESC back")
        hint = self.small.render(hints, True, (130, 155, 175))
        self.screen.blit(hint, (int(40 * self.sx), footer_y))
        if self.status:
            status = self.small.render(self.status, True, (130, 225, 165))
            self.screen.blit(status, (int(40 * self.sx), h - int(20 * self.sy)))
        pygame.display.flip()



    def run(self, config):
        cfg = normalize_config(config)
        self.profile = cfg.get("default_workload", "medium")
        self.selected, self.scroll = 0, 0
        self.status = ""
        self.quit = False
        while True:
            rows = self._rows()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.quit = True
                    return cfg
                if event.type == pygame.MOUSEWHEEL:
                    self.scroll -= event.y * 2
                    continue
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for name, rect in self._tab_rects(cfg):
                        if rect.collidepoint(event.pos):
                            self.profile = name
                            self.selected, self.scroll = 0, 0
                            break
                    else:
                        top = int(168 * self.sy)
                        row_h = int(26 * self.sy)
                        if event.pos[1] >= top:
                            index = self.scroll + (event.pos[1] - top) // row_h
                            if 0 <= index < len(rows):
                                self.selected = index
                    continue
                if event.type != pygame.KEYDOWN:
                    continue
                key = event.key
                if key == pygame.K_ESCAPE:
                    return cfg
                if key == pygame.K_UP:
                    self.selected = max(0, self.selected - 1)
                elif key == pygame.K_DOWN:
                    self.selected = min(len(rows) - 1, self.selected + 1)
                elif key == pygame.K_PAGEUP:
                    self.selected = max(0, self.selected - self._visible_count())
                elif key == pygame.K_PAGEDOWN:
                    self.selected = min(len(rows) - 1,
                                        self.selected + self._visible_count())
                elif key in (pygame.K_LEFT, pygame.K_RIGHT):
                    spec = rows[self.selected]
                    direction = -1 if key == pygame.K_LEFT else 1
                    multiplier = 5 if pygame.key.get_mods() & pygame.KMOD_SHIFT else 1
                    try:
                        adjust_value(cfg, spec.path, direction * spec.step * multiplier)
                        cfg = self._save(cfg)
                    except Exception as exc:
                        self.status = f"invalid value: {exc}"
                elif key in (pygame.K_1, pygame.K_2, pygame.K_3):
                    names = list(cfg["profiles"])
                    index = key - pygame.K_1
                    if index < len(names):
                        self.profile = names[index]
                        self.selected, self.scroll = 0, 0
                        self.status = f"editing profile: {self.profile}"
                elif key == pygame.K_s:
                    cfg = self._save(cfg)
                elif key == pygame.K_r:
                    cfg = load_config()
                    self.profile = cfg.get("default_workload", self.profile)
                    self.selected, self.scroll = 0, 0
                    self.status = "reloaded from disk"
                elif key == pygame.K_d:
                    cfg["default_workload"] = self.profile
                    cfg = self._save(cfg)
                    self.status = f"default profile: {self.profile}"
                elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    cfg = self._save(cfg)
            self._ensure_visible()
            self._draw(cfg)
            self.clock.tick(60)
