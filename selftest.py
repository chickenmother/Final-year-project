"""Run on X and on Y (python selftest.py). The printed hash MUST be identical on both machines."""
import hashlib, json, platform, socket, sys
from common.game import Game
import pygame
import PIL
import websockets

def script(i):
    return ("d" if i % 120 < 60 else "a") + ("w" if i % 200 < 100 else "s") + (" " if i % 15 == 0 else "")

def digest(g):
    return hashlib.md5(json.dumps(g.snapshot(), sort_keys=True).encode()).hexdigest()

print("host:", socket.gethostname(), "|", platform.platform())
print("python", sys.version.split()[0], "| pygame", pygame.version.ver,
      "| pillow", PIL.__version__, "| websockets", websockets.__version__)

g = Game()
mid = None
for i in range(3000):
    g.step(script(i))
    if i == 1000:
        mid = json.loads(json.dumps(g.snapshot()))      # goes through JSON like it would on the network
print("ticks", g.tick, "score", g.score, "deaths", g.deaths, "hash", digest(g))

g2 = Game(seed=999)                                     # different seed, then restore a snapshot
g2.restore(mid)
for i in range(1001, 3000):
    g2.step(script(i))
print("resync OK" if digest(g2) == digest(g) else "resync MISMATCH  <-- BUG")
print("render bytes:", len(g.render((960, 540), 80)), "(X)", len(g.render((480, 270), 40, smooth=False)), "(Y)")
