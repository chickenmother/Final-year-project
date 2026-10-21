# ---- EDIT THESE TWO LINES ON ALL 3 MACHINES (use `ipconfig` to find them) ----
X_IP = "192.168.1.10"   # desktop  (cloud X)
Y_IP = "192.168.1.11"   # laptop A (edge gateway Y)

#testing on my local machine, so I just use localhost for both
#X_IP = "127.0.0.1"
#Y_IP = "127.0.0.1"
# ------------------------------------------------------------------------------

X_PORT, Y_PORT_Z, Y_PORT_DASH = 8001, 8000, 8002
X_URI = f"ws://{X_IP}:{X_PORT}"
Y_URI = f"ws://{Y_IP}:{Y_PORT_Z}"

TICK_RATE = 60          # game ticks per second (each tick = 4 original 240 FPS frames)
X_STREAM_EVERY = 1      # X sends a frame every tick -> 60 fps
Y_STREAM_EVERY = 2      # Y sends a frame every 2nd tick -> 30 fps

WIN_W, WIN_H = 960, 540             # window on Z
X_SIZE, X_QUALITY = (960, 540), 80  # cloud X: high quality
Y_SIZE, Y_QUALITY = (480, 270), 40  # edge Y: low quality (weaker node)

HIGH_MS, LOW_MS = 80, 50   # RTT(X<->Y) thresholds: > HIGH -> use Y, < LOW -> back to X
BAD_COUNT = 3              # consecutive bad pings (0.2 s apart) before switching to Y
RECOVER_S = 3.0            # RTT must stay < LOW_MS this long before switching back to X
