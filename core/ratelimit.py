# core/ratelimit.py
"""
Request rate limiting.

Storage is in-process, so limits are per instance. With one Render service
that is exact; if you ever scale to several, an attacker gets the limit
multiplied by the instance count. Move to Redis storage at that point.
"""
import os

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

# Tunable without a deploy.
LOGIN_LIMIT = os.getenv("RATE_LIMIT_LOGIN", "10/minute")
REGISTER_LIMIT = os.getenv("RATE_LIMIT_REGISTER", "30/hour")


def client_ip(request: Request) -> str:
    """
    The real client address.

    Render terminates TLS at a proxy, so request.client.host is the proxy.
    Without this every visitor shares a single bucket and the limit either
    blocks everyone or nobody.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # First entry is the original client; the rest are proxies.
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=client_ip)