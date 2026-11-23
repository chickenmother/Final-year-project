"""Rolling encoder statistics for Cloud X (WS2.3).

X measures every encoded frame (encode time, size, keyframe flag) and pushes a
1 Hz summary to Y, which copies it into the dashboard state, the report samples
and the control panel.  Dependency-free so it can be unit-tested without PyAV,
sockets or a clock.
"""
from __future__ import annotations

import collections
import time

from common.testplan import percentile

EMPTY = {"fps": 0.0, "encode_p50": None, "encode_p95": None,
         "keyframes_s": 0.0, "frame_kb": 0.0, "frames": 0}


class FrameStats:
    """Sliding window of encoded frames; ``snapshot()`` is the wire payload."""

    def __init__(self, window_s=2.0, clock=None):
        self.window_s = max(0.5, float(window_s))
        self._clock = clock or time.monotonic
        self._frames = collections.deque()      # (t, encode_ms, nbytes, key)

    def add(self, encode_ms, nbytes, key=False, when=None):
        now = self._clock() if when is None else float(when)
        self._frames.append((now, float(encode_ms), int(nbytes), bool(key)))
        self._prune(now)

    def reset(self):
        self._frames.clear()

    def mature(self, when=None, min_span=0.5):
        """True once the window spans enough time for meaningful rates.

        X skips the first snapshot after a preset swap or a start, otherwise a
        single forced IDR in a 0.25 s window reads as 4 keyframes/s.
        """
        now = self._clock() if when is None else float(when)
        self._prune(now)
        return bool(self._frames) and (now - self._frames[0][0]) >= min_span

    def snapshot(self, when=None):
        """fps, encode p50/p95 (ms), keyframes/s, mean frame size (KB)."""
        now = self._clock() if when is None else float(when)
        self._prune(now)
        if not self._frames:
            return dict(EMPTY)
        first = self._frames[0][0]
        # A short window (first second after a rebuild) still needs a sane
        # divisor; clamp to 0.25 s so one early frame does not report 200 fps.
        span = max(0.25, min(self.window_s, now - first))
        encodes = [frame[1] for frame in self._frames]
        sizes = [frame[2] for frame in self._frames]
        keys = sum(1 for frame in self._frames if frame[3])
        return {
            "fps": round(len(self._frames) / span, 1),
            "encode_p50": round(percentile(encodes, 0.50), 2),
            "encode_p95": round(percentile(encodes, 0.95), 2),
            "keyframes_s": round(keys / span, 2),
            "frame_kb": round(sum(sizes) / len(sizes) / 1024, 1),
            "frames": len(self._frames),
        }

    def _prune(self, now):
        limit = now - self.window_s
        while self._frames and self._frames[0][0] < limit:
            self._frames.popleft()
