"""Shared slowapi limiter instance.

Defined in its own module so route-owning modules (e.g. runtime_engine) can
apply the SAME limiter that app.py registers on app.state, without importing
the 8,000-line app.py (which would be circular). app.py imports `limiter` from
here and sets `app.state.limiter = limiter`.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
