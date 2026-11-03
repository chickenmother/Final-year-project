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

def _pair(name, default):
    w, h = os.environ.get(name, default).lower().split("x")
    return int(w), int(h)


TICK_RATE = 60          # game ticks per second (each tick = 4 original 240 FPS frames)
X_STREAM_EVERY = int(os.environ.get("FYP_X_STREAM_EVERY", "1"))   # 1 -> 60 fps
Y_STREAM_EVERY = int(os.environ.get("FYP_Y_STREAM_EVERY", "2"))   # 2 -> 30 fps

WIN_W, WIN_H = _pair("FYP_WIN_SIZE", "960x540")        # window on Z
X_SIZE = _pair("FYP_X_SIZE", "960x540")                # cloud X capture size
Y_SIZE = _pair("FYP_Y_SIZE", "480x270")                # edge Y capture size
X_QUALITY = int(os.environ.get("FYP_X_QUALITY", "80"))
Y_QUALITY = int(os.environ.get("FYP_Y_QUALITY", "40"))

# RTT(X<->Y) thresholds: > HIGH_MS -> use Y, < LOW_MS -> back to X.
# On a WAN calibrate these around the measured baseline: HIGH ~= p50 + 35, LOW ~= p50 + 15.
HIGH_MS = float(os.environ.get("FYP_HIGH_MS", "80"))
LOW_MS = float(os.environ.get("FYP_LOW_MS", "50"))
BAD_COUNT = int(os.environ.get("FYP_BAD_COUNT", "3"))         # bad pings before switching to Y
RECOVER_S = float(os.environ.get("FYP_RECOVER_S", "3.0"))     # time below LOW_MS to go back to X

# Z measures the Z<->Y hop by sending {"pts": <clock>} every N input messages; Y echoes it.
Z_PING_EVERY = int(os.environ.get("FYP_Z_PING_EVERY", "6"))
