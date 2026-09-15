"""
Rate limiting (Section 22). Applied specifically to /auth/login and
/auth/register -- the two endpoints most exposed to brute-force and
credential-stuffing attacks, since they're the only ones reachable without
an existing valid token.

Keyed by client IP by default. Honest limitation: this means a shared IP
(office NAT, corporate proxy) shares one limit across everyone behind it --
a real production deployment behind a load balancer/reverse proxy should
also confirm X-Forwarded-For is being trusted correctly, which depends on
the specific hosting setup and isn't something this code alone can
guarantee.

In-memory storage by default (fine for a single-process deployment). If
you run multiple app instances behind a load balancer, the limit won't be
shared across them -- see slowapi's Redis storage backend if that matters
for your deployment.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
