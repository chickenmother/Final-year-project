"""Task-oriented game simulation (Milestone 1).

This is a new, deterministic core. The legacy ``common/game.py`` remains the
default so the existing simulator and self-test keep working; this core can be
selected with ``FYP_GAME_CORE=v2`` once integrated.
"""
import hashlib
import json
import math
import random

import pygame

from . import render as render_mod
from .effects import ParticlePool
from .entities import Bot, Bullet, Obstacle, Player
from .hitreg import SpatialGrid, apply_damage, push_out
from .settings import normalize_config, profile_from_config, tuning_from_config
from .workload import WorkloadConfig


class Game:
    def __init__(self, workload="light", seed=12345, config=None):
        self.config = normalize_config(config)
        self.workload = (workload if isinstance(workload, WorkloadConfig)
                         else profile_from_config(self.config, workload))
        self.tuning = tuning_from_config(self.config)
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.effects = ParticlePool(max_particles=self.tuning.max_particles,
                                    seed=self.seed + 1)
        self.grid = SpatialGrid()
        self.tick = 0
        self.score = 0
        self.deaths = 0
        self.wave = 1
        self.game_over = False
        self.prev_space = False
        self.player_hit_cooldown = 0.0
        self.reset()

    # ---------------- setup ----------------
    def reset(self):
        w, h = self.workload.width, self.workload.height
        size = self.tuning.player.size
        self.player = Player(w // 2 - size // 2, h // 2 - size // 2,
                             w=size, h=size,
                             max_hp=self.tuning.player.max_hp,
                             speed=self.tuning.player.speed)
        self.bullets = []
        self.bots = []
        self.obstacles = []
        self.score = 0
        self.deaths = 0
        self.wave = 1
        self.tick = 0
        self.game_over = False
        self.prev_space = False
        self.player_hit_cooldown = 0.0
        self.effects.clear()
        self._spawn_obstacles(self.workload.obstacles)
        self._spawn_bots(self.workload.bots)
        self.grid.rebuild(self.obstacles)

    def _spawn_obstacles(self, count):
        w, h = self.workload.width, self.workload.height
        limit = max(0, int(count))

        # Small counts fit with random placement. Large counts use a jittered
        # grid so the heavy profile can actually reach its target density.
        tune = self.tuning.obstacle
        if limit <= 60:
            attempts = 0
            while len(self.obstacles) < limit and attempts < limit * 30 + 50:
                attempts += 1
                size = self.rng.randrange(tune.size_min,
                                         max(tune.size_min + 1, tune.size_max))
                rect = pygame.Rect(
                    self.rng.randrange(0, max(1, w - size)),
                    self.rng.randrange(0, max(1, h - size)),
                    size, size,
                )
                if rect.colliderect(self.player.rect.inflate(180, 180)):
                    continue
                if any(rect.colliderect(o.rect) for o in self.obstacles):
                    continue
                self.obstacles.append(Obstacle(rect.x, rect.y, rect.w, rect.h))
            return

        cols = max(1, int(math.ceil(math.sqrt(limit * w / h))))
        rows = max(1, int(math.ceil(limit / cols)))
        cell_w, cell_h = w / cols, h / rows
        max_size = max(18, int(min(cell_w, cell_h) * 0.55))
        for i in range(limit):
            cx = (i % cols + 0.5) * cell_w + (self.rng.random() - 0.5) * cell_w * 0.5
            cy = (i // cols + 0.5) * cell_h + (self.rng.random() - 0.5) * cell_h * 0.5
            size = self.rng.randrange(
                tune.large_size_min,
                max(tune.large_size_min + 1, min(tune.large_size_max, max_size)),
            )
            rect = pygame.Rect(int(cx - size / 2), int(cy - size / 2), size, size)
            if rect.colliderect(self.player.rect.inflate(120, 120)):
                continue
            self.obstacles.append(Obstacle(rect.x, rect.y, rect.w, rect.h))

    def _spawn_bots(self, count):
        w, h = self.workload.width, self.workload.height
        tune = self.tuning.bot
        limit = max(0, int(count))
        attempts = 0
        while len(self.bots) < limit and attempts < limit * 40 + 50:
            attempts += 1
            rect = pygame.Rect(
                self.rng.randrange(0, max(1, w - tune.size)),
                self.rng.randrange(0, max(1, h - tune.size)),
                tune.size, tune.size,
            )
            clearance = self.player.rect.inflate(tune.spawn_clearance, tune.spawn_clearance)
            if rect.colliderect(clearance):
                continue
            if any(rect.colliderect(b.rect) for b in self.bots):
                continue
            bot = Bot(rect.x, rect.y, w=tune.size, h=tune.size,
                      speed=tune.speed, max_hp=tune.max_hp)
            span = tune.initial_fire_max - tune.initial_fire_min
            bot.fire_cooldown = tune.initial_fire_min + self.rng.random() * span
            self.bots.append(bot)

    # ---------------- helpers ----------------
    def _clamp(self, rect):
        rect.clamp_ip(pygame.Rect(0, 0, self.workload.width, self.workload.height))

    def _explode(self, x, y, color=(255, 170, 60)):
        self.effects.spawn(x, y, self.workload.particles_per_explosion, color)

    def _shoot(self, owner, x, y, vx, vy, damage):
        self.bullets.append(Bullet(int(x), int(y), vx, vy, owner, damage))

    def _player_shoot(self):
        if self.player.cooldown > 0.0:
            return
        rate = max(0.1, float(self.workload.bullets_per_second))
        self.player.cooldown = max(0.05, 1.0 / rate)
        self._shoot(
            "player",
            self.player.rect.centerx - 4,
            self.player.rect.top - 16,
            0.0, -self.tuning.player.bullet_velocity,
            self.tuning.player.bullet_damage,
        )

    def _bot_shoot(self, bot):
        dx = self.player.rect.centerx - bot.rect.centerx
        dy = self.player.rect.centery - bot.rect.centery
        dist = math.hypot(dx, dy) or 1.0
        speed = self.tuning.bot.bullet_velocity
        self._shoot(
            "bot",
            bot.rect.centerx - 4,
            bot.rect.centery - 8,
            speed * dx / dist,
            speed * dy / dist,
            self.tuning.bot.bullet_damage,
        )

    # ---------------- frame ----------------
    def _update_bullet(self, bullet, dt):
        bullet.rect.x += int(bullet.vx * dt)
        bullet.rect.y += int(bullet.vy * dt)
        if not (0 <= bullet.rect.centerx <= self.workload.width):
            return "remove"
        if not (0 <= bullet.rect.centery <= self.workload.height):
            return "remove"

        for obstacle in self.grid.query(bullet.rect):
            if obstacle.hp <= 0:
                continue
            if bullet.rect.colliderect(obstacle.rect):
                if apply_damage(obstacle, bullet.damage):
                    obstacle.hp = 0
                    self._explode(obstacle.rect.centerx, obstacle.rect.centery,
                                  (180, 160, 140))
                    if bullet.owner == "player":
                        self.score += 10
                return "remove"

        if bullet.owner == "player":
            for bot in self.bots:
                if bot.hp <= 0:
                    continue
                if bullet.rect.colliderect(bot.rect):
                    if apply_damage(bot, bullet.damage):
                        bot.hp = 0
                        self._explode(bot.rect.centerx, bot.rect.centery)
                        self.score += 100
                    return "remove"
        else:
            if bullet.rect.colliderect(self.player.rect):
                self.player.hp -= bullet.damage
                return "remove"
        return None

    def _update_bot(self, bot, dt):
        tune = self.tuning.bot
        dx = self.player.rect.centerx - bot.rect.centerx
        dy = self.player.rect.centery - bot.rect.centery
        dist = math.hypot(dx, dy) or 1.0
        if dist > tune.stop_range:
            bot.rect.x += int(bot.speed * dx / dist)
            bot.rect.y += int(bot.speed * dy / dist)
        elif dist < tune.retreat_range:
            bot.rect.x -= int(bot.speed * dx / dist)
            bot.rect.y -= int(bot.speed * dy / dist)

        for obstacle in self.grid.query(bot.rect):
            if bot.rect.colliderect(obstacle.rect):
                px, py = push_out(bot.rect, obstacle.rect)
                bot.rect.x += int(px)
                bot.rect.y += int(py)
        self._clamp(bot.rect)

        bot.fire_cooldown -= dt
        if dist < tune.fire_range and bot.fire_cooldown <= 0.0:
            self._bot_shoot(bot)
            span = tune.fire_cooldown_max - tune.fire_cooldown_min
            bot.fire_cooldown = tune.fire_cooldown_min + self.rng.random() * span

    def step(self, keys):
        if self.game_over:
            return
        dt = 1.0 / max(1, self.workload.tick_rate)
        self.tick += 1
        self.player.cooldown = max(0.0, self.player.cooldown - dt)
        self.player_hit_cooldown = max(0.0, self.player_hit_cooldown - dt)

        dx = ("d" in keys) - ("a" in keys)
        dy = ("s" in keys) - ("w" in keys)
        if dx:
            self.player.rect.x += int(dx * self.player.speed)
        if dy:
            self.player.rect.y += int(dy * self.player.speed)
        self._clamp(self.player.rect)

        for obstacle in self.grid.query(self.player.rect):
            if self.player.rect.colliderect(obstacle.rect):
                px, py = push_out(self.player.rect, obstacle.rect)
                self.player.rect.x += int(px)
                self.player.rect.y += int(py)
                if self.player_hit_cooldown <= 0.0:
                    self.player.hp -= self.tuning.player.obstacle_damage
                    self.player_hit_cooldown = self.tuning.player.obstacle_hit_cooldown
                break

        space = " " in keys
        if space and not self.prev_space:
            self._player_shoot()
        self.prev_space = space

        for bot in self.bots:
            self._update_bot(bot, dt)

        kept = []
        for bullet in self.bullets:
            if self._update_bullet(bullet, dt) != "remove":
                kept.append(bullet)
        self.bullets = kept

        self.bots = [b for b in self.bots if b.hp > 0]
        before = len(self.obstacles)
        self.obstacles = [o for o in self.obstacles if o.hp > 0]
        if len(self.obstacles) != before:
            self.grid.rebuild(self.obstacles)

        for bot in self.bots:
            if self.player.rect.colliderect(bot.rect):
                px, py = push_out(self.player.rect, bot.rect)
                self.player.rect.x += int(px)
                self.player.rect.y += int(py)
                if self.player_hit_cooldown <= 0.0:
                    self.player.hp -= self.tuning.player.bot_damage
                    self.player_hit_cooldown = self.tuning.player.bot_hit_cooldown
                break

        self.effects.update(dt)

        if self.player.hp <= 0:
            self.player.hp = 0
            if not self.game_over:
                self.deaths += 1
            self.game_over = True
            self._explode(self.player.rect.centerx, self.player.rect.centery,
                          (255, 120, 80))
        elif self.workload.bots > 0 and not self.bots:
            self.wave += 1
            count = min(self.workload.bots + self.wave * 2, self.workload.bots * 2)
            self._spawn_bots(count)

    # ---------------- sync ----------------
    def snapshot(self):
        v, internal, g = self.rng.getstate()
        return dict(
            workload=self.workload.name,
            tick=self.tick, score=self.score, deaths=self.deaths, wave=self.wave,
            game_over=self.game_over, prev_space=self.prev_space,
            player_hit_cooldown=self.player_hit_cooldown,
            player=[self.player.rect.x, self.player.rect.y, self.player.hp,
                    self.player.cooldown, self.player.hit_cooldown],
            bots=[[b.rect.x, b.rect.y, b.hp, b.cooldown, b.fire_cooldown]
                  for b in self.bots],
            bullets=[[b.rect.x, b.rect.y, b.vx, b.vy, b.owner, b.damage]
                     for b in self.bullets],
            obstacles=[[o.rect.x, o.rect.y, o.rect.w, o.rect.h, o.hp]
                       for o in self.obstacles],
            rng=[v, list(internal), g],
        )

    def restore(self, state):
        name = state.get("workload")
        if name and name != self.workload.name:
            self.workload = profile_from_config(self.config, name)
        self.tick = state["tick"]
        self.score = state["score"]
        self.deaths = state.get("deaths", 0)
        self.wave = state["wave"]
        self.game_over = state["game_over"]
        self.prev_space = state["prev_space"]
        self.player_hit_cooldown = state["player_hit_cooldown"]

        p = state["player"]
        player_tune = self.tuning.player
        self.player = Player(p[0], p[1], w=player_tune.size, h=player_tune.size,
                             max_hp=player_tune.max_hp, speed=player_tune.speed)
        self.player.hp = p[2]
        self.player.cooldown = p[3]
        self.player.hit_cooldown = p[4]

        self.bots = []
        bot_tune = self.tuning.bot
        for x, y, hp, cooldown, fire_cooldown in state["bots"]:
            bot = Bot(x, y, w=bot_tune.size, h=bot_tune.size,
                      speed=bot_tune.speed, max_hp=bot_tune.max_hp)
            bot.hp, bot.cooldown, bot.fire_cooldown = hp, cooldown, fire_cooldown
            self.bots.append(bot)

        self.bullets = [Bullet(b[0], b[1], b[2], b[3], b[4], b[5])
                        for b in state["bullets"]]
        self.obstacles = []
        for o in state["obstacles"]:
            obstacle = Obstacle(o[0], o[1], o[2], o[3], self.tuning.obstacle.max_hp)
            obstacle.hp = o[4]
            self.obstacles.append(obstacle)
        v, internal, g = state["rng"]
        self.rng.setstate((v, tuple(internal), g))
        self.effects.clear()
        self.grid.rebuild(self.obstacles)

    def digest(self):
        data = json.dumps(self.snapshot(), sort_keys=True).encode()
        return hashlib.md5(data).hexdigest()

    # ---------------- rendering ----------------
    def render_surface(self, size, smooth=True):
        return render_mod.render_surface(self, size, smooth)

    def render_image(self, size, smooth=True):
        return render_mod.render_image(self, size, smooth)

    def render(self, size, quality, smooth=True):
        return render_mod.render_jpeg(self, size, quality, smooth)

