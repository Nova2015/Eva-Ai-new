"""
EVA local-only egress guard.

When EVA_LOCAL_ONLY=1 this module (installed on import) refuses every network
connection from this Python process except loopback and, by default, private-LAN
addresses. Hostnames are NEVER resolved unless they are on the allow-list, so
there is no DNS leak either. Each blocked destination is logged once and
appended to eva_blocked_hosts.log, which makes it a leak finder: run EVA normally
in local-only mode, use every feature, then read the log.

Environment:
  EVA_LOCAL_ONLY=1               turn the guard on (off = this module does nothing)
  EVA_LOCAL_GUARD_MODE=block     block (default) | log (record only, do NOT block)
  EVA_LOCAL_ALLOW_LAN=1          allow private-LAN IPs such as 192.168.x.x (default 1)
  EVA_LOCAL_ALLOW_HOSTS=a,b      extra host names that may be resolved (e.g. a LAN server)
  EVA_LOCAL_GUARD_LOG=path       blocked-host log (default eva_blocked_hosts.log)

Limits (it is a safety net, not a firewall):
  * only Python's socket layer is covered. gRPC (C core), subprocesses and any
    native library that opens its own sockets are NOT seen.
  * it protects THIS process only. The browser runs the frontend separately.
For a hard guarantee add an OS firewall rule as well.
"""
import errno
import ipaddress
import logging
import os
import socket
import threading
import time

logger = logging.getLogger("eva_local_guard")

_TRUE = ("1", "true", "yes")
ENABLED = os.getenv("EVA_LOCAL_ONLY", "").strip().lower() in _TRUE
MODE = os.getenv("EVA_LOCAL_GUARD_MODE", "block").strip().lower()
ALLOW_LAN = os.getenv("EVA_LOCAL_ALLOW_LAN", "1").strip().lower() in _TRUE
LOG_PATH = os.getenv("EVA_LOCAL_GUARD_LOG", "eva_blocked_hosts.log")
_ALLOWED_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "host.docker.internal"} | {
    h.strip().lower() for h in os.getenv("EVA_LOCAL_ALLOW_HOSTS", "").split(",") if h.strip()
}


class EgressBlocked(OSError):
    """Raised instead of opening a connection that local-only mode forbids."""


_seen = set()
_lock = threading.Lock()
_installed = False

_orig_getaddrinfo = socket.getaddrinfo
_orig_gethostbyname = socket.gethostbyname
_orig_gethostbyname_ex = socket.gethostbyname_ex
_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
_orig_sendto = socket.socket.sendto


def _ip_allowed(text: str) -> bool:
    try:
        ip = ipaddress.ip_address(text.split("%")[0])
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    if ip.is_loopback or ip.is_unspecified:
        return True
    return bool(ALLOW_LAN and (ip.is_private or ip.is_link_local))


def _host_allowed(host) -> bool:
    if host is None:
        return True
    if isinstance(host, (bytes, bytearray)):
        host = bytes(host).decode("ascii", "ignore")
    h = str(host).strip().lower().rstrip(".")
    if h == "" or h in _ALLOWED_NAMES:
        return True
    try:
        ipaddress.ip_address(h.split("%")[0])
    except ValueError:
        return False          # a name that is not allow-listed: never resolve it
    return _ip_allowed(h)


def _record(host, how: str) -> None:
    key = str(host)
    with _lock:
        new = key not in _seen
        _seen.add(key)
    if not new:
        return
    verdict = "BLOCKED" if MODE == "block" else "logged, NOT blocked"
    logger.warning("EVA local-only: outbound %s to %r - %s", how, host, verdict)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{how}\t{host}\t{verdict}\n")
    except Exception:
        pass


def _check(host, how: str) -> None:
    if _host_allowed(host):
        return
    _record(host, how)
    if MODE == "block":
        raise EgressBlocked(errno.ENETUNREACH, f"EVA local-only mode blocked outbound {how} to {host!r}")


def _g_getaddrinfo(host, *a, **k):
    _check(host, "dns")
    return _orig_getaddrinfo(host, *a, **k)


def _g_gethostbyname(host):
    _check(host, "dns")
    return _orig_gethostbyname(host)


def _g_gethostbyname_ex(host):
    _check(host, "dns")
    return _orig_gethostbyname_ex(host)


def _addr_host(sock, address):
    if sock.family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple) and address:
        return address[0]
    return None


def _g_connect(self, address):
    h = _addr_host(self, address)
    if h is not None:
        _check(h, "connect")
    return _orig_connect(self, address)


def _g_connect_ex(self, address):
    h = _addr_host(self, address)
    if h is not None:
        _check(h, "connect")
    return _orig_connect_ex(self, address)


def _g_sendto(self, data, *args):
    h = _addr_host(self, args[-1] if args else None)
    if h is not None:
        _check(h, "udp-send")
    return _orig_sendto(self, data, *args)


def install() -> bool:
    """Install the guard (idempotent). Returns True when it is active."""
    global _installed
    if not ENABLED:
        return False
    if _installed:
        return True
    # Model hubs must not be contacted either; models have to be cached already.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    socket.getaddrinfo = _g_getaddrinfo
    socket.gethostbyname = _g_gethostbyname
    socket.gethostbyname_ex = _g_gethostbyname_ex
    socket.socket.connect = _g_connect
    socket.socket.connect_ex = _g_connect_ex
    socket.socket.sendto = _g_sendto
    _installed = True
    logger.warning("EVA local-only egress guard ACTIVE (mode=%s, lan=%s, log=%s)", MODE, ALLOW_LAN, LOG_PATH)
    return True


def blocked_hosts():
    """Destinations seen so far (blocked, or logged in log mode)."""
    with _lock:
        return sorted(_seen)


install()


if __name__ == "__main__":
    import sys
    print(f"ENABLED={ENABLED} MODE={MODE} ALLOW_LAN={ALLOW_LAN}")
    if not ENABLED:
        sys.exit("Set EVA_LOCAL_ONLY=1 and run again to self-test.")
    for host, port in (("127.0.0.1", 1), ("example.com", 80), ("8.8.8.8", 53)):
        try:
            socket.create_connection((host, port), timeout=1).close()
            print(f"{host}:{port} -> connected")
        except EgressBlocked as e:
            print(f"{host}:{port} -> BLOCKED ({e})")
        except OSError as e:
            print(f"{host}:{port} -> allowed by guard, connection failed normally ({type(e).__name__})")
    print("seen:", blocked_hosts())
