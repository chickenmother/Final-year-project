"""
Headless, deterministic port of Space_2D_Shotting_Game/main.py.
SAME FILE runs on X and Y. Rules/speeds/sizes are copied from the original.

Changes vs the original (needed for the network setup):
  * all randomness comes from a private seeded RNG        -> X and Y stay identical
  * input is passed in as a string of keys ("w","a","s","d"," ") instead of read from the keyboard
  * original ran at 240 FPS; we run 60 network ticks/s, each tick = 4 original frames (SUBSTEPS)
  * when the player crashes the game restarts (original just quit) so the test can run forever
  * pygame sprites replaced by plain Rects so the state is easy to snapshot
"""
import io
import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")        # no window on X / Y
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame
from PIL import Image

WIDTH, HEIGHT = 1600, 900
SUBSTEPS = 4
BLACK = (0, 0, 0)
IMG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "images")

pygame.display.init()
pygame.display.set_mode((1, 1))


def _img(name):
    return pygame.image.load(os.path.join(IMG_DIR, name)).convert()


BG = _img("background.png")
BULLET_IMG = pygame.transform.scale(_img("bullet.png"), (40, 60))
BULLET_IMG.set_colorkey(BLACK)
PLAYER_IMG = _img("player.jpg")
PLAYER_IMG.set_colorkey(BLACK)
ROCK_IMG = _img("rock.png")
PLAYER_SIZE = PLAYER_IMG.get_size()
PLAYER_RADIUS = 25.5

_SCREEN = pygame.Rect(0, 0, WIDTH, HEIGHT)
_FRAME = pygame.Surface((WIDTH, HEIGHT))
_rock_cache = {}


def _rock_surf(w):
    s = _rock_cache.get(w)
    if s is None:
        s = pygame.transform.scale(ROCK_IMG, (w, w))
        s.set_colorkey(BLACK)
        _rock_cache[w] = s
    return s


class Rock:
    __slots__ = ("rect", "speedy")


class Game:
    def __init__(self, seed=12345):
        self.rng = random.Random(seed)
        self.tick = 0
        self.deaths = 0
        self.score = 0
        self.prev_space = False
        self._reset()

    # ---------------- logic ----------------
    def _new_rock(self):
        swh = self.rng.randrange(30, 70)
        rect = pygame.Rect(0, 0, swh, swh)
        x = self.rng.randrange(0, WIDTH)
        y = self.rng.randrange(-100, -40)
        rect.center = (x, y)
        r = Rock()
        r.rect = rect
        r.speedy = self.rng.randrange(1, 10)
        return r

    def _reset(self):
        self.player = pygame.Rect(0, 0, *PLAYER_SIZE)
        self.player.center = (WIDTH // 2, HEIGHT // 2)
        self.bullets = []
        self.rocks = [self._new_rock() for _ in range(8)]

    def _shoot(self):
        b = pygame.Rect(0, 0, 40, 60)
        b.bottom = self.player.top
        b.centerx = self.player.centerx
        self.bullets.append(b)

    def _frame(self, dx, dy):                      # one ORIGINAL frame (speedx = 5)
        p = self.player
        p.x += 5 * dx
        p.y += 5 * dy
        p.clamp_ip(_SCREEN)
        for r in self.rocks:
            rc = r.rect
            rc.y += r.speedy
            if rc.top > HEIGHT or rc.left > WIDTH or rc.left < 0:
                rc.x = self.rng.randrange(0, WIDTH)
                rc.y = self.rng.randrange(-100, -40)
                r.speedy = self.rng.randrange(1, 10)
        for b in self.bullets:
            b.y -= 10
        self.bullets = [b for b in self.bullets if b.bottom >= 0]

        # bullets vs rocks (groupcollide(rocks, bullets, True, True))
        dead_b, kept, n_hit = set(), [], 0
        for r in self.rocks:
            hit = False
            for j, b in enumerate(self.bullets):
                if j not in dead_b and r.rect.colliderect(b):
                    hit = True
                    dead_b.add(j)
            if hit:
                n_hit += 1
            else:
                kept.append(r)
        if n_hit:
            self.bullets = [b for j, b in enumerate(self.bullets) if j not in dead_b]
            for _ in range(n_hit):
                kept.append(self._new_rock())
            self.rocks = kept
            self.score += n_hit

        # player vs rocks (collide_circle)
        for r in self.rocks:
            ddx = p.centerx - r.rect.centerx
            ddy = p.centery - r.rect.centery
            if ddx * ddx + ddy * ddy <= (PLAYER_RADIUS + r.rect.width / 2) ** 2:
                self.deaths += 1
                self._reset()
                break

    def step(self, keys):
        space = " " in keys
        shoot = space and not self.prev_space      # KEYDOWN, not "held"
        self.prev_space = space
        self.tick += 1
        dx = ("d" in keys) - ("a" in keys)
        dy = ("s" in keys) - ("w" in keys)
        for i in range(SUBSTEPS):
            if i == 0 and shoot:
                self._shoot()
            self._frame(dx, dy)

    # ---------------- sync ----------------
    def snapshot(self):
        v, internal, g = self.rng.getstate()
        return dict(
            tick=self.tick, deaths=self.deaths, score=self.score, prev_space=self.prev_space,
            player=[self.player.x, self.player.y],
            rocks=[[r.rect.x, r.rect.y, r.rect.w, r.rect.h, r.speedy] for r in self.rocks],
            bullets=[[b.x, b.y] for b in self.bullets],
            rng=[v, list(internal), g],
        )

    def restore(self, s):
        self.tick, self.deaths, self.score, self.prev_space = s["tick"], s["deaths"], s["score"], s["prev_space"]
        self.player = pygame.Rect(s["player"][0], s["player"][1], *PLAYER_SIZE)
        self.rocks = []
        for x, y, w, h, sp in s["rocks"]:
            r = Rock()
            r.rect = pygame.Rect(x, y, w, h)
            r.speedy = sp
            self.rocks.append(r)
        self.bullets = [pygame.Rect(x, y, 40, 60) for x, y in s["bullets"]]
        v, internal, g = s["rng"]
        self.rng.setstate((v, tuple(internal), g))

    # ---------------- rendering (the ONLY part that differs in quality X vs Y) ----------------
    def render(self, size, quality, smooth=True):
        f = _FRAME
        f.fill(BLACK)
        f.blit(BG, (0, 0))
        f.blit(PLAYER_IMG, self.player)
        for r in self.rocks:
            f.blit(_rock_surf(r.rect.w), r.rect)
        for b in self.bullets:
            f.blit(BULLET_IMG, b)
        small = (pygame.transform.smoothscale if smooth else pygame.transform.scale)(f, size)
        buf = io.BytesIO()
        Image.frombytes("RGB", size, pygame.image.tobytes(small, "RGB")).save(buf, "JPEG", quality=quality)
        return buf.getvalue()
