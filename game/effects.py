"""Visual particle effects (explosions)."""
import math
import random

from .entities import Particle


class ParticlePool:
    """Fixed-budget particle pool; particles are visual only.

    Particles use their own RNG so adding visuals cannot change the gameplay
    RNG or the determinism hash.
    """

    def __init__(self, max_particles=5000, seed=1):
        self.max_particles = int(max_particles)
        self.rng = random.Random(seed)
        self.particles = []

    def clear(self):
        self.particles.clear()

    def spawn(self, x, y, count, color=(255, 170, 60)):
        room = self.max_particles - len(self.particles)
        if room <= 0:
            return 0
        count = min(int(count), room)
        for _ in range(count):
            angle = self.rng.random() * 2.0 * math.pi
            speed = 30.0 + self.rng.random() * 220.0
            life = 0.25 + self.rng.random() * 0.65
            self.particles.append(Particle(
                float(x), float(y),
                speed * math.cos(angle),
                speed * math.sin(angle),
                life, color, 1 + self.rng.random() * 2.5,
            ))
        return count

    def update(self, dt):
        if not self.particles:
            return
        alive = []
        for p in self.particles:
            p.life -= dt
            if p.life <= 0.0:
                continue
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.vy += 180.0 * dt          # light gravity
            alive.append(p)
        self.particles = alive

    def __len__(self):
        return len(self.particles)
