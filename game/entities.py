"""Game entities for the task-based core."""
import pygame


class Player:
    __slots__ = ("rect", "hp", "max_hp", "cooldown", "speed", "hit_cooldown")

    def __init__(self, x, y, w=48, h=48, max_hp=100, speed=7.0):
        self.rect = pygame.Rect(x, y, w, h)
        self.max_hp = int(max_hp)
        self.hp = self.max_hp
        self.cooldown = 0.0
        self.speed = float(speed)   # pixels per tick
        self.hit_cooldown = 0.0


class Bot:
    __slots__ = ("rect", "hp", "max_hp", "cooldown", "speed", "fire_cooldown")

    def __init__(self, x, y, w=44, h=44, speed=2.2, max_hp=50):
        self.rect = pygame.Rect(x, y, w, h)
        self.max_hp = int(max_hp)
        self.hp = self.max_hp
        self.cooldown = 0.0
        self.speed = float(speed)
        # time until the next shot; seeded by the simulation RNG
        self.fire_cooldown = 0.8


class Obstacle:
    __slots__ = ("rect", "hp", "max_hp")

    def __init__(self, x, y, w, h, hp=100):
        self.rect = pygame.Rect(x, y, w, h)
        self.max_hp = hp
        self.hp = hp


class Bullet:
    __slots__ = ("rect", "vx", "vy", "owner", "damage")

    def __init__(self, x, y, vx, vy, owner, damage=10, w=8, h=16):
        self.rect = pygame.Rect(x, y, w, h)
        self.vx = vx
        self.vy = vy
        self.owner = owner          # "player" or "bot"
        self.damage = damage


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "color", "radius")

    def __init__(self, x, y, vx, vy, life, color, radius):
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.life = life
        self.max_life = life
        self.color = color
        self.radius = radius
