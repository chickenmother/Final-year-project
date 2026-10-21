"""Shared configuration. The SAME file is used unchanged on all three machines.

Each tier only needs the address of the tier it CONNECTS TO:
  Cloud X  : nothing            (binds 0.0.0.0 on X_PORT)
  Middle Y : FYP_X_IP           (address of Cloud X)
  End Z    : FYP_Y_IP           (address of Middle Y)

The run_*.ps1 launchers set these variables for you. For a single-machine demo
the defaults (127.0.0.1) are correct and no configuration is needed.
"""
import os

# bind addresses, never connect targets
X_HOST = os.environ.get("FYP_X_HOST", "0.0.0.0")
Y_HOST = os.environ.get("FYP_Y_HOST", "0.0.0.0")

# connect targets (use `ipconfig` to find each machine's LAN address)
X_IP = os.environ.get("FYP_X_IP", "127.0.0.1")   # read by Middle Y
Y_IP = os.environ.get("FYP_Y_IP", "127.0.0.1")   # read by End Z / dashboard

X_PORT = int(os.environ.get("FYP_X_PORT", "8001"))
Y_PORT_Z = int(os.environ.get("FYP_Y_PORT_Z", "8000"))
Y_PORT_DASH = int(os.environ.get("FYP_Y_PORT_DASH", "8002"))

X_URI = os.environ.get("FYP_X_URI", f"ws://{X_IP}:{X_PORT}")
Y_URI = os.environ.get("FYP_Y_URI", f"ws://{Y_IP}:{Y_PORT_Z}")

# websocket keepalive: a dead Wi-Fi link is detected in ~PING_INTERVAL + PING_TIMEOUT
PING_INTERVAL = float(os.environ.get("FYP_PING_INTERVAL", "15"))
PING_TIMEOUT = float(os.environ.get("FYP_PING_TIMEOUT", "15"))
RECONNECT_S = 2.0       # wait before dialling X / Y again

TICK_RATE = 60          # game ticks per second (each tick = 4 original 240 FPS frames)
X_STREAM_EVERY = 1      # X sends a frame every tick -> 60 fps
Y_STREAM_EVERY = 2      # Y sends a frame every 2nd tick -> 30 fps

WIN_W, WIN_H = 960, 540             # window on Z
X_SIZE, X_QUALITY = (960, 540), 80  # cloud X: high quality
Y_SIZE, Y_QUALITY = (480, 270), 40  # edge Y: low quality (weaker node)

HIGH_MS, LOW_MS = 80, 50   # RTT(X<->Y) thresholds: > HIGH -> use Y, < LOW -> back to X
BAD_COUNT = 3              # consecutive bad pings (0.2 s apart) before switching to Y
RECOVER_S = 3.0            # RTT must stay < LOW_MS this long before switching back to X
