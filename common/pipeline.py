"""WS3.5: stage-chain execution shared by EDGE Y and CLOUD X.

``common.placement`` describes *where* each task runs; this module turns that
description into the small set of decisions an executor needs per tick:

* which stage runs next and whether that is a network crossing,
* which stages a tier can run back-to-back without crossing,
* which channel carries a crossing (JSON state, or rendered pixels for D->E),
* per-run counters for the report (crossings, channels, stalls).

Nothing here touches sockets, pygame or the game: the gateways stay the only
place with I/O, and the tests can drive the whole chain without a network.
"""
import json
import struct

from common.placement import STAGES, next_stage, resolve_chain

STATE = "state"
PIXELS = "pixels"
CHANNELS = (STATE, PIXELS)
PIXEL_FORMATS = ("jpeg", "raw")          # raw is opt-in (2.8 MB/frame at 720p)


class PipelineError(ValueError):
    """A chain that cannot be executed as asked."""


class Chain:
    """A validated stage -> tier table with routing helpers.

    ``Chain(tasks)`` accepts any A-E assignment (L stays on X, which
    :func:`common.placement.validate` enforces upstream).  U is local to Z
    and never appears here.
    """

    def __init__(self, tasks):
        chain = resolve_chain(tasks)
        self.tasks = dict(chain["stages"])
        self.stream_tier = chain["stream_tier"]
        self.pixel_channel = chain["pixel_channel"]
        self.crossings = list(chain["crossings"])

    # -- shape ---------------------------------------------------------
    @property
    def pattern(self):
        """``{"A": "X", ...}`` as the wire/report form."""
        return dict(self.tasks)

    def owner(self, stage):
        return self.tasks[_stage(stage)]

    def stages_of(self, tier):
        tier = str(tier).strip().upper()
        return [stage for stage in STAGES if self.tasks[stage] == tier]

    def route(self, stage):
        """Where ``stage`` runs, what follows it and how that is shipped."""
        stage = _stage(stage)
        nxt = next_stage(stage)
        next_tier = self.tasks[nxt] if nxt else None
        crossing = bool(nxt) and next_tier != self.tasks[stage]
        return {"stage": stage,
                "tier": self.tasks[stage],
                "next": nxt,
                "next_tier": next_tier,
                "next_owner": next_tier,
                "crossing": crossing,
                "kind": ((PIXELS if nxt == "E" else STATE)
                         if crossing else None)}

    def first(self):
        """Routing entry for A: the tick always starts at the chain head."""
        return self.route("A")

    def local_run(self, stage, tier):
        """Longest run of stages from ``stage`` that ``tier`` executes alone.

        Returns ``(stages, forward)``: the stages to execute in order, and the
        next stage to ship elsewhere (``None`` once E has run).  A stage the
        tier does not own yields ``([], stage)`` so the caller forwards it.
        """
        tier = str(tier).strip().upper()
        stages = []
        while stage is not None and self.tasks[stage] == tier:
            stages.append(stage)
            stage = next_stage(stage)
        return stages, stage

    def describe(self):
        from common.placement import describe_chain
        return describe_chain(self.tasks)

    def __eq__(self, other):
        return isinstance(other, Chain) and other.tasks == self.tasks

    def __repr__(self):
        return f"Chain({self.tasks})"


def _stage(stage):
    stage = str(stage).strip().upper()
    if stage not in STAGES:
        raise PipelineError(f"unknown stage {stage!r}")
    return stage


def plan_tick(chain, tier, keys=""):
    """What the tier that owns A does for one tick (dry-run helper).

    Returns ``{"run": [stages...], "forward": stage|None, "kind": ...}``; the
    executors follow the same rules live, so a plan can be unit-tested.
    """
    if not isinstance(chain, Chain):
        chain = Chain(chain)
    tier = str(tier).strip().upper()
    entry = chain.first()
    if entry["tier"] != tier:
        return {"run": [], "forward": "A", "kind": STATE}
    run, forward = chain.local_run("A", tier)
    kind = None
    if forward is not None:
        kind = PIXELS if forward == "E" else STATE
    return {"run": run, "forward": forward, "kind": kind}


def pixel_format(raw=False, quality=None):
    """Report label for the D->E channel: ``jpeg85`` / ``raw``."""
    if raw:
        return "raw"
    if quality:
        return f"jpeg{int(quality)}"
    return "jpeg"


class ChannelStats:
    """Per-run counters for the WS3.5 report fields.

    A "stall" is a tick whose crossing could not be sent (link down or the
    peer's queue full).  Stalls are counted, never fatal: a measurement with a
    few stalls is still a measurement, and the count says how many.
    """

    def __init__(self):
        self.state_msgs = 0
        self.state_bytes = 0
        self.pixel_msgs = 0
        self.pixel_bytes = 0
        self.mirror_msgs = 0
        self.mirror_bytes = 0
        self.pixel_fmt = None
        self.stalls = 0
        self.stall_ticks = []
        self.encode_frames = 0
        self.encode_ms = 0.0
        self.stage_ms = {stage: 0.0 for stage in STAGES}
        self.stage_n = {stage: 0 for stage in STAGES}

    def crossing(self, kind, nbytes):
        if kind == PIXELS:
            self.pixel_msgs += 1
            self.pixel_bytes += int(nbytes)
        else:
            self.state_msgs += 1
            self.state_bytes += int(nbytes)

    def stall(self, tick=None):
        self.stalls += 1
        if tick is not None and len(self.stall_ticks) < 50:
            self.stall_ticks.append(int(tick))

    def mirror(self, nbytes):
        """State echoed back to keep Y's mirror current (E ran on X)."""
        self.mirror_msgs += 1
        self.mirror_bytes += int(nbytes)

    def set_pixel_format(self, fmt):
        """Remember which pixel encoding the D->E channel actually used."""
        if fmt:
            self.pixel_fmt = str(fmt)

    def stage(self, stage, ms):
        stage = _stage(stage)
        self.stage_ms[stage] += float(ms)
        self.stage_n[stage] += 1

    def stage_p50(self):
        """Mean ms per stage (the report labels it ``stage_p50`` anyway)."""
        return {stage: (round(self.stage_ms[stage] / self.stage_n[stage], 2)
                        if self.stage_n[stage] else None)
                for stage in STAGES}

    def encoded(self, ms=0.0):
        self.encode_frames += 1
        self.encode_ms += float(ms)

    def snapshot(self):
        return {
            "state_msgs": self.state_msgs,
            "state_bytes": self.state_bytes,
            "pixel_msgs": self.pixel_msgs,
            "pixel_bytes": self.pixel_bytes,
            "mirror_msgs": self.mirror_msgs,
            "mirror_bytes": self.mirror_bytes,
            "pixel_fmt": self.pixel_fmt,
            "stalls": self.stalls,
            "stall_ticks": list(self.stall_ticks),
            "encode_frames": self.encode_frames,
            "stage_p50": self.stage_p50(),
        }


def merge_channels(into, other):
    """Fold ``other``'s counters into ``into`` (in place) and return ``into``."""
    for name in ("state_msgs", "state_bytes", "pixel_msgs", "pixel_bytes",
                 "mirror_msgs", "mirror_bytes", "stalls", "encode_frames",
                 "encode_ms"):
        setattr(into, name, getattr(into, name) + getattr(other, name))
    for stage in STAGES:
        into.stage_ms[stage] += other.stage_ms[stage]
        into.stage_n[stage] += other.stage_n[stage]
    for tick in other.stall_ticks:
        if len(into.stall_ticks) < 50:
            into.stall_ticks.append(tick)
    return into


def report_fields(channels, x_channels, chain=None, pixels_fmt=None,
                  encode_fps=None):
    """The WS3.5 keys a report always carries.

    A preset run has no chain, so it records ``crossings: 0`` / ``stalls: 0``
    and empty channels rather than omitting the keys — the comparison tooling
    then reads the same shape for every pattern.
    """
    channels = dict(channels or {})
    x_channels = dict(x_channels or {})
    return {
        "chain": chain.pattern if chain is not None else {},
        "crossings": len(chain.crossings) if chain is not None else 0,
        "stream_tier": chain.stream_tier if chain is not None else None,
        "pixels_format": (channels.get("pixel_fmt")
                          or (pixels_fmt if chain is not None else None)),
        "channels": channels,
        "channels_x": x_channels,
        "stalls": (int(channels.get("stalls") or 0)
                   + int(x_channels.get("stalls") or 0)),
        "encode_fps": encode_fps if chain is not None else None,
        "stage_p50": channels.get("stage_p50") or {},
        "stage_p50_x": x_channels.get("stage_p50") or {},
    }


# ---------------------------------------------------------------------------
# Wire format for the custom chain (WS3.5).
#
# JSON messages (both directions):
#   {"t": "stage", "stage": "C", "tick": 41, "seq": 900, "keys": "d",
#    "s": {...snapshot...}}        s is present when the state must travel
#   {"t": "final", "tick": 41, "seq": 900, "s": {...}}
#   {"t": "stride", "src": "x", "n": 1}     Z: expected tick stride, 0=any
#
# Pixels (D here, E there) are binary so no base64 cost:
#   b"p" | tick (4) | seq (4) | head_len (4) | head JSON | pixel bytes
#   head = {"fmt": "jpeg85"|"raw", "size": [w, h], "s": {...snapshot...}}
PIXELS_MARK = b"p"


def stage_message(stage, tick, seq, keys="", snapshot=None):
    """JSON for "run ``stage`` for tick ``tick``" (sent to the other tier)."""
    out = {"t": "stage", "stage": _stage(stage), "tick": int(tick),
           "seq": int(seq), "keys": keys or ""}
    if snapshot is not None:
        out["s"] = snapshot
    return json.dumps(out)


def parse_stage(m):
    """Validated ``(stage, tick, seq, keys, snapshot)`` from a stage message."""
    stage = _stage(m.get("stage"))
    try:
        tick, seq = int(m.get("tick")), int(m.get("seq"))
    except (TypeError, ValueError):
        raise PipelineError(f"bad stage tick/seq in {m!r}") from None
    return stage, tick, seq, m.get("keys") or "", m.get("s")


def final_message(tick, seq, snapshot):
    """JSON echo of the finished tick, so Y's own copy stays current."""
    return json.dumps({"t": "final", "tick": int(tick), "seq": int(seq),
                       "s": snapshot})


def stride_message(src, n):
    """Tell End Z how many ticks the sender skips (0 = irregular, no IDR)."""
    return json.dumps({"t": "stride", "src": str(src), "n": int(n)})


def pixels_message(tick, seq, fmt, size, snapshot, data):
    """Binary D->E frame: tick/seq, a JSON head and the raw pixel payload."""
    head = json.dumps({"fmt": fmt, "size": [int(size[0]), int(size[1])],
                       "s": snapshot}).encode()
    return (PIXELS_MARK + struct.pack("!III", int(tick), int(seq), len(head))
            + head + data)


def parse_pixels(msg):
    """``(tick, seq, fmt, size, snapshot, data)`` or ``None`` if malformed."""
    if not isinstance(msg, (bytes, bytearray)) or msg[:1] != PIXELS_MARK:
        return None
    if len(msg) < 13:
        return None
    tick, seq, head_len = struct.unpack("!III", msg[1:13])
    head_end = 13 + head_len
    if len(msg) < head_end:
        return None
    try:
        head = json.loads(msg[13:head_end])
    except ValueError:
        return None
    size = head.get("size") or [0, 0]
    return (tick, seq, str(head.get("fmt") or "jpeg"), tuple(size),
            head.get("s"), msg[head_end:])


def bytes_per_tick(channel, nbytes, tick_rate):
    """KB/s label for a channel's payload (report + panel)."""
    if not tick_rate:
        return 0.0
    return round(int(nbytes) * float(tick_rate) / 1024.0, 1)
