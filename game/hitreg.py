"""Collision / hit-registration helpers.

Obstacles are static, so they are indexed once in a uniform grid. Bullets and
actors query only nearby cells instead of checking every obstacle.
"""
import pygame


class SpatialGrid:
    def __init__(self, cell_size=128):
        self.cell_size = max(16, int(cell_size))
        self.cells = {}

    def _key(self, x, y):
        return int(x // self.cell_size), int(y // self.cell_size)

    def rebuild(self, obstacles):
        self.cells.clear()
        for obstacle in obstacles:
            r = obstacle.rect
            x0, y0 = self._key(r.left, r.top)
            x1, y1 = self._key(r.right, r.bottom)
            for cx in range(x0, x1 + 1):
                for cy in range(y0, y1 + 1):
                    self.cells.setdefault((cx, cy), []).append(obstacle)

    def query(self, rect):
        """Yield obstacles whose grid cells overlap ``rect``, without duplicates."""
        x0, y0 = self._key(rect.left, rect.top)
        x1, y1 = self._key(rect.right, rect.bottom)
        seen = set()
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                for obstacle in self.cells.get((cx, cy), ()):
                    if id(obstacle) in seen:
                        continue
                    seen.add(id(obstacle))
                    yield obstacle


def hits(a, b):
    return a.colliderect(b)


def apply_damage(entity, amount):
    """Subtract HP and return True when the entity is eliminated."""
    entity.hp -= amount
    return entity.hp <= 0


def push_out(rect, obstacle_rect):
    """Move a rect minimally out of an obstacle and return the push vector."""
    if not rect.colliderect(obstacle_rect):
        return 0, 0
    left = rect.right - obstacle_rect.left
    right = obstacle_rect.right - rect.left
    top = rect.bottom - obstacle_rect.top
    bottom = obstacle_rect.bottom - rect.top
    smallest = min(left, right, top, bottom)
    if smallest == left:
        return -left, 0
    if smallest == right:
        return right, 0
    if smallest == top:
        return 0, -top
    return 0, bottom


__all__ = ["SpatialGrid", "hits", "apply_damage", "push_out"]
