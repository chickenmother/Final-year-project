"""Small network helpers shared by the tiers."""
import logging
import socket

from websockets.exceptions import InvalidMessage


def quiet_handshake_errors():
    """Hide the traceback websockets logs when a plain TCP probe connects.

    Setup checks such as `Test-NetConnection <host> -Port 8001` open the socket
    and close it without an HTTP upgrade, so websockets reports an invalid
    handshake. That is expected; drop only those records so real server errors
    stay visible.
    """
    class _Filter(logging.Filter):
        def filter(self, record):
            exc = record.exc_info[1] if record.exc_info else None
            return not isinstance(exc, InvalidMessage)

    logging.getLogger("websockets.server").addFilter(_Filter())


def lan_ip():
    """Best-effort LAN address that the other machines can dial.

    Uses the default route to pick the right interface; no packet is sent.
    A VPN client may make this return the tunnel address, which is a good
    reminder to switch the VPN off before running the demo.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()
