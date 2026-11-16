"""Rendering for the task-based game core."""
import io
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame
from PIL import Image

IMG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "images")

pygame.display.init()
pygame.display.set_mode((1, 1))


def _load(name, fallback_size, fallback_color):
    path = os.path.join(IMG_DIR, name)
    try:
        return pygame.image.load(path).convert()
    except Exception:
        surf = pygame.Surface(fallback_size)
        surf.fill(fallback_color)
        return surf


_BG = _load("background.png", (1600, 900), (10, 12, 24))
_PLAYER = _load("player.jpg", (48, 48), (80, 200, 120))
_ROCK = _load("rock.png", (64, 64), (120, 110, 100))
_BULLET = _load("bullet.png", (8, 16), (255, 230, 80))

_frames = {}
_rock_cache = {}
_bg_cache = {}
_player_cache = {}


def _frame(world_w, world_h):
    key = (world_w, world_h)
    if key not in _frames:
        _frames[key] = pygame.Surface((world_w, world_h))
    return _frames[key]


def _background(world_w, world_h):
    key = (world_w, world_h)
    surf = _bg_cache.get(key)
    if surf is None:
        surf = pygame.transform.smoothscale(_BG, key)
        _bg_cache[key] = surf
    return surf


def _player(size):
    key = tuple(size)
    surf = _player_cache.get(key)
    if surf is None:
        surf = pygame.transform.smoothscale(_PLAYER, key)
        _player_cache[key] = surf
    return surf


def _rock(w):
    w = max(1, int(w))
    surf = _rock_cache.get(w)
    if surf is None:
        surf = pygame.transform.scale(_ROCK, (w, w))
        _rock_cache[w] = surf
    return surf


def _hp_bar(surf, rect, hp, max_hp, color=(80, 220, 120)):
    if max_hp <= 0:
        return
    width = max(1, rect.width)
    h = 4
    x, y = rect.left, rect.top - 7
    pygame.draw.rect(surf, (40, 40, 40), (x, y, width, h))
    frac = max(0.0, min(1.0, hp / max_hp))
    pygame.draw.rect(surf, color, (x, y, int(width * frac), h))


def render_surface(game, size, smooth=True):
    world_w, world_h = game.workload.width, game.workload.height
    frame = _frame(world_w, world_h)
    frame.fill((0, 0, 0))
    frame.blit(_background(world_w, world_h), (0, 0))

    for obstacle in game.obstacles:
        frame.blit(_rock(obstacle.rect.width), obstacle.rect)

    for bot in game.bots:
        pygame.draw.rect(frame, (210, 90, 70), bot.rect)
        pygame.draw.rect(frame, (255, 210, 120), bot.rect, 2)
        _hp_bar(frame, bot.rect, bot.hp, bot.max_hp, (230, 90, 90))

    frame.blit(_player(game.player.rect.size), game.player.rect)
    _hp_bar(frame, game.player.rect, game.player.hp, game.player.max_hp)

    for bullet in game.bullets:
        pygame.draw.rect(frame, (255, 225, 90), bullet.rect)

    for p in game.effects.particles:
        pygame.draw.circle(frame, p.color, (int(p.x), int(p.y)), max(1, int(p.radius)))

    if size == (world_w, world_h):
        return frame
    scaler = pygame.transform.smoothscale if smooth else pygame.transform.scale
    return scaler(frame, size)


def to_image(surface):
    return Image.frombytes("RGB", surface.get_size(), pygame.image.tobytes(surface, "RGB"))


def render_image(game, size, smooth=True):
    return to_image(render_surface(game, size, smooth))


def render_jpeg(game, size, quality, smooth=True):
    buf = io.BytesIO()
    render_image(game, size, smooth).save(buf, "JPEG", quality=int(quality))
    return buf.getvalue()
