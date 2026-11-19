"""H.264 encode/decode helpers for the cloud and edge video streams.

PyAV is imported by Cloud X and Middle Y (encoders) and End Z (decoder).
Any tier without it falls back to JPEG, so the simulator still runs.
"""
from fractions import Fraction

import av


class H264Encoder:
    """Low-latency H.264 encoder (libx264 by default, optional hardware)."""

    def __init__(self, size, fps, bitrate=1_000_000, gop=10, encoder=None,
                 intra_refresh=False):
        self.size = size
        self.fps = max(1, int(fps))
        self.bitrate = int(bitrate)
        self.gop = max(1, int(gop))
        self.encoder = (encoder or "libx264").lower()
        self.intra_refresh = bool(intra_refresh)
        self.pts = 0
        self.force_next_keyframe = False
        self.codec = None
        self.name = None
        self.pix_fmt = None
        self._open()

    def _open(self):
        # libx264 is the default because QSV at 1080p was ~32 ms/frame on the
        # test laptop; libx264 ultrafast was ~2 ms/frame. Hardware encoders can
        # be selected with FYP_X_ENCODER / FYP_Y_ENCODER.
        #
        # scenecut=0 is important for jitter: by default x264 inserts an IDR at
        # every scene change, which in this game means 100-200 KB keyframe
        # bursts several times per second. A fixed long GOP plus IDR-on-request
        # keeps the frame sizes smooth.
        kbps = max(100, self.bitrate // 1000)
        x264_params = (f"scenecut=0:keyint={self.gop}:min-keyint={self.gop}"
                       f":bframes=0:rc-lookahead=0:ipratio=1.1"
                       f":vbv-maxrate={kbps}:vbv-bufsize={max(100, kbps // 2)}")
        if self.intra_refresh:
            x264_params += ":intra-refresh=1"
        available = {
            "libx264": ("yuv420p", {"preset": "ultrafast", "tune": "zerolatency",
                                    "x264-params": x264_params}),
            "h264_qsv": ("nv12",
                         {"async_depth": "1", "low_delay_brc": "1",
                          "preset": "veryfast"}),
            "h264_nvenc": ("yuv420p", {}),
        }
        order = [self.encoder]
        if self.encoder != "libx264":
            order.append("libx264")
        candidates = [(name,) + available[name] for name in order if name in available]
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
        return self._encode_frame(frame)

    def encode_surface(self, surface):
        """Encode a pygame surface without a PIL round-trip.

        ``pygame.image.tobytes`` + ``VideoFrame.from_bytes`` is measurably
        cheaper than ``to_image`` + ``VideoFrame.from_image`` at 1920x1080.
        """
        import pygame

        w, h = surface.get_size()
        raw = pygame.image.tobytes(surface, "RGBA")
        frame = av.VideoFrame.from_bytes(raw, w, h, format="rgba")
        return self._encode_frame(frame)

    def _encode_frame(self, frame):
        if frame.format.name != self.pix_fmt:
            frame = frame.reformat(format=self.pix_fmt)
        if self.force_next_keyframe:
            frame.pict_type = av.video.frame.PictureType.I
            self.force_next_keyframe = False
        frame.pts = self.pts
        self.pts += 1
        out = []
        for packet in self.codec.encode(frame):
            out.append((bytes(packet), bool(packet.is_keyframe)))
        return out

    def force_keyframe(self):
        """Make the next encoded frame an IDR without re-opening the encoder."""
        self.force_next_keyframe = True

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
