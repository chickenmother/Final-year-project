"""H.264 encode/decode helpers for the cloud and edge video streams.

PyAV is imported by Cloud X and Middle Y (encoders) and End Z (decoder).
Any tier without it falls back to JPEG, so the simulator still runs.
"""
from fractions import Fraction

import av


class H264Encoder:
    """Low-latency H.264 encoder with a hardware-first fallback chain."""

    def __init__(self, size, fps, bitrate=1_000_000, gop=10):
        self.size = size
        self.fps = max(1, int(fps))
        self.bitrate = int(bitrate)
        self.gop = max(1, int(gop))
        self.pts = 0
        self.codec = None
        self.name = None
        self.pix_fmt = None
        self._open()

    def _open(self):
        candidates = [
            ("h264_qsv", "nv12",
             {"async_depth": "1", "low_delay_brc": "1", "preset": "veryfast"}),
            ("h264_nvenc", "yuv420p", {}),
            ("libx264", "yuv420p",
             {"preset": "ultrafast", "tune": "zerolatency"}),
        ]
        last = None
        for name, pix_fmt, options in candidates:
            try:
                codec = av.CodecContext.create(name, "w")
                codec.width, codec.height = self.size
                codec.pix_fmt = pix_fmt
                codec.time_base = Fraction(1, self.fps)
                codec.framerate = Fraction(self.fps, 1)
                codec.bit_rate = self.bitrate
                codec.gop_size = self.gop
                codec.max_b_frames = 0
                codec.options = options
                codec.open()
                self.codec, self.name, self.pix_fmt = codec, name, pix_fmt
                return
            except Exception as exc:          # try the next encoder
                last = exc
        raise RuntimeError(f"no H.264 encoder available: {last}")

    def encode(self, image):
        """Encode one PIL image; returns [(payload_bytes, is_keyframe), ...]."""
        frame = av.VideoFrame.from_image(image)
        if frame.format.name != self.pix_fmt:
            frame = frame.reformat(format=self.pix_fmt)
        frame.pts = self.pts
        self.pts += 1
        out = []
        for packet in self.codec.encode(frame):
            out.append((bytes(packet), bool(packet.is_keyframe)))
        return out

    def force_keyframe(self):
        """Re-open the encoder so the next frame is an IDR with fresh SPS/PPS."""
        self.codec = None
        self._open()

    def close(self):
        if self.codec is not None:
            try:
                for _ in self.codec.encode(None):
                    pass
            except Exception:
                pass
            self.codec = None


class H264Decoder:
    """Decode raw H.264 packets into PIL images."""

    def __init__(self):
        self.codec = av.CodecContext.create("h264", "r")

    def reset(self):
        self.codec = av.CodecContext.create("h264", "r")

    def decode(self, data):
        try:
            frames = self.codec.decode(av.Packet(data))
        except Exception:
            self.reset()
            return []
        return [frame.to_image() for frame in frames]
