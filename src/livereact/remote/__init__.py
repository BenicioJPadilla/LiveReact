"""Phone console: a token-protected web page on the venue Wi-Fi that can only
make the show SAFER (blackout on, dim, cap strobe, disarm lasers), never more
intense. See remote/server.py."""

from __future__ import annotations

from .server import PhoneConsole, PhoneServer, make_token

__all__ = ["PhoneConsole", "PhoneServer", "make_token"]
