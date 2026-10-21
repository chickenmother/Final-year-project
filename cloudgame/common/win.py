def hires_timer():
    """Ask Windows for 1 ms timer resolution (default 15.6 ms makes 60 Hz ticks bursty)."""
    try:
        import ctypes
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass
