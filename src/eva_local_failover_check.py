"""EVA Server Local — A/B failover verification.

An operational check, not a unit test: it drives the SAME routing the /chat path
uses (providers.configured / failover_chain / dispatch) against real machines
over real HTTP, and reports which machine actually served each request using the
per-machine telemetry rather than a probe of its own.

Deliberately NOT named test_*.py. There is no pytest config in this repo, so
test_*.py is collected from anywhere — and this file does real inference and, in
lifecycle mode, stops processes. It must never run inside the unit suite.

Two modes:

  observe (default)
      Read-only. Never starts or stops anything, so it is safe against the real
      Machine A and Machine B — which are separate hosts this process has no
      business killing. You take a machine down by hand; this reports what the
      router did about it. Use --expect to assert a specific machine served.

  lifecycle (--lifecycle)
      Dev-box only. Starts and stops LOCAL Ollama servers itself to walk the
      whole matrix unattended. Requires the machines to be on loopback.

Config comes from the same environment production reads (EVA_LOCAL_A_URL,
EVA_LOCAL_A_MODEL, EVA_LOCAL_B_URL, EVA_LOCAL_B_MODEL, EVA_LOCAL_ENABLED); no
model, URL or runtime is hardcoded here.

  python -m eva_local_failover_check                      # what serves right now
  python -m eva_local_failover_check --expect A           # assert A serves
  python -m eva_local_failover_check --cloud              # include the cloud leg
  python -m eva_local_failover_check --lifecycle          # full matrix, dev box

Exit code is 0 when every check passed, 1 otherwise, so it can gate a rollout.
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import providers  # noqa: E402

PROBE = [{"role": "user", "content": "Reply with exactly one word: ok"}]
PROBE_TOKENS = 16
# Bounded so a stalled cloud provider cannot hang an operational check; the
# cloud SDKs carry no explicit timeout of their own.
CLOUD_DEADLINE_S = float(os.getenv("EVA_LOCAL_CHECK_CLOUD_DEADLINE_S", "25"))


# ── reporting ────────────────────────────────────────────────────────────────
class Report:
    def __init__(self) -> None:
        self.checks: List[tuple] = []

    def record(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, ok, detail))

    def render(self) -> int:
        if not self.checks:
            return 0
        print("\n" + "=" * 74 + "\nVERDICT\n" + "=" * 74)
        for name, ok, detail in self.checks:
            print("  [%s] %-46s %s" % ("PASS" if ok else "FAIL", name, detail))
        failed = [c for c in self.checks if not c[1]]
        print("\n%d/%d passed" % (len(self.checks) - len(failed), len(self.checks)))
        return 1 if failed else 0


# ── machine telemetry ────────────────────────────────────────────────────────
def machine_requests() -> Dict[str, int]:
    """Per-machine request counts straight from the provider's own health, so
    "who served this" comes from production telemetry and not a side channel."""
    return {m["machine"]: m["health"]["requests"]
            for m in providers.eva_local_status()["machines"] if m["configured"]}


def served_by(before: Dict[str, int], after: Dict[str, int]) -> str:
    hit = [m for m in sorted(after) if after.get(m, 0) > before.get(m, 0)]
    return "+".join(hit) if hit else "-"


def ask(label: str, allow_cloud: bool) -> Dict[str, Any]:
    """One turn down the real routing path, exactly as the chat fallback goes."""
    before = machine_requests()
    t0 = time.time()
    local_ok = providers.configured("eva_local")
    chain = [pid for pid, _ in providers.failover_chain()]
    answer, who, errors = "", "", []
    if local_ok:
        try:
            answer = providers.dispatch("eva_local", PROBE, max_tokens=PROBE_TOKENS)
            who = "LOCAL"
        except Exception as exc:
            errors.append("local:" + providers.classify_error(exc))
    if not answer and allow_cloud:
        for pid in [p for p in chain if p != "eva_local"]:
            got, err = _bounded_dispatch(pid)
            if got:
                answer, who = got, pid.upper()
                break
            errors.append("%s:%s" % (pid, err))
    ms = int((time.time() - t0) * 1000)
    after = machine_requests()
    machine = served_by(before, after)
    print("  %-30s served=%-9s machine=%-4s %6dms local=%-5s chain=%s"
          % (label, who or "NONE", machine, ms, local_ok, chain))
    print("       answer=%-24r %s" % ((answer or "")[:22],
                                      ("errors=" + " ".join(errors)) if errors else ""))
    return {"who": who, "machine": machine, "ms": ms, "local": local_ok,
            "chain": chain, "answer": answer, "errors": errors}


def _bounded_dispatch(pid: str):
    """Run one cloud call under a deadline, on a thread, so a provider that
    never answers cannot wedge the check."""
    import threading
    box: Dict[str, str] = {}

    def call() -> None:
        try:
            box["ans"] = providers.dispatch(pid, PROBE, max_tokens=PROBE_TOKENS)
        except Exception as exc:
            box["err"] = providers.classify_error(exc)

    th = threading.Thread(target=call, daemon=True)
    th.start()
    th.join(CLOUD_DEADLINE_S)
    if box.get("ans"):
        return box["ans"], ""
    return "", box.get("err") or ("NO_ANSWER_IN_%ss" % int(CLOUD_DEADLINE_S))


def show_telemetry() -> None:
    st = providers.eva_local_status()
    print("\n" + "=" * 74 + "\nPer-machine telemetry\n" + "=" * 74)
    print("  selected_machine =", st.get("selected_machine"))
    for m in st["machines"]:
        if not m["configured"]:
            print("  machine %s  not configured (%s)" % (m["machine"], m["detail"]))
            continue
        h = m["health"]
        print("  machine %s  model=%-18s requests=%-4s failures=%-4s "
              "last_error=%-9s skipped_now=%s"
              % (m["machine"], m["model"], h["requests"], h["failures"],
                 h.get("last_error_code"), m["skipped_now"]))
    agg = providers.eva_local_health()
    print("  aggregate    requests=%-4s failures=%-4s last_error=%s"
          % (agg["requests"], agg["failures"], agg.get("last_error_code")))


# ── local process control (lifecycle mode only) ──────────────────────────────
def _port_of(url: str) -> Optional[int]:
    try:
        p = urlparse(url)
        if p.hostname not in ("127.0.0.1", "localhost", "::1"):
            return None
        return p.port
    except Exception:
        return None


def up(port: int, timeout: float = 0.4) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def _ps(cmd: str) -> None:
    """Fire a PowerShell command with NO pipes. A launched server inherits the
    parent's stdout handle, so a captured pipe never reaches EOF and the call
    blocks forever in subprocess's post-timeout communicate()."""
    subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)


def stop_port(port: int) -> bool:
    """Stop the listener AND its children. Ollama spawns llama-server as a child
    that survives a plain Stop-Process on the parent; those orphans hold on to
    the memory the next model load needs, which looks like an unrelated OOM."""
    _ps("$ids = Get-NetTCPConnection -LocalPort %d -State Listen -EA SilentlyContinue "
        "| Select-Object -ExpandProperty OwningProcess; "
        "foreach ($id in $ids) { "
        "  Get-CimInstance Win32_Process -Filter \"ParentProcessId=$id\" -EA SilentlyContinue "
        "  | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue }; "
        "  Stop-Process -Id $id -Force -EA SilentlyContinue }" % port)
    for _ in range(80):
        if not up(port):
            return True
        time.sleep(0.25)
    return False


def start_port(port: int) -> bool:
    exe = os.getenv("EVA_LOCAL_OLLAMA_BIN", "ollama")
    models = os.getenv("EVA_LOCAL_OLLAMA_MODELS", "")
    keep = os.getenv("EVA_LOCAL_OLLAMA_KEEP_ALIVE", "-1")
    env = ('$env:OLLAMA_KEEP_ALIVE="%s"; $env:OLLAMA_HOST="127.0.0.1:%d"; ' % (keep, port))
    if models:
        env = ('$env:OLLAMA_MODELS="%s"; ' % models) + env
    _ps(env + 'Start-Process -FilePath "%s" -ArgumentList "serve" -WindowStyle Hidden' % exe)
    for _ in range(160):
        if up(port):
            return True
        time.sleep(0.25)
    return False


# ── modes ────────────────────────────────────────────────────────────────────
def mode_observe(args, rep: Report) -> None:
    print("=" * 74 + "\nObserve: what serves right now\n" + "=" * 74)
    r = ask("current routing", allow_cloud=args.cloud)
    if args.expect:
        want = args.expect.upper()
        if want == "CLOUD":
            rep.record("cloud serves", bool(r["answer"]) and r["who"] not in ("", "LOCAL"),
                       "served=%s" % (r["who"] or "NONE"))
            rep.record("local reported unavailable", r["local"] is False,
                       "configured=%s" % r["local"])
        else:
            rep.record("machine %s serves" % want, r["machine"].endswith(want),
                       "machine=%s" % r["machine"])
            rep.record("machine %s answered" % want, bool(r["answer"]),
                       "answer=%r" % (r["answer"] or "")[:16])
    if args.repeat > 1:
        for i in range(2, args.repeat + 1):
            ask("repeat %d" % i, allow_cloud=args.cloud)


def mode_lifecycle(args, rep: Report) -> None:
    cfgs = {c["machine"]: c for c in providers.eva_local_candidates()}
    ports = {m: _port_of(c["base_url"]) for m, c in cfgs.items()}
    if sorted(ports) != ["A", "B"] or any(p is None for p in ports.values()):
        print("lifecycle mode needs Machine A and Machine B both configured on "
              "loopback; found %r." % {m: c["base_url"] for m, c in cfgs.items()})
        print("Against real hosts use observe mode: take a machine down yourself, "
              "then run with --expect B.")
        rep.record("lifecycle preconditions", False, "machines are not local")
        return

    print("=" * 74 + "\n1. A ON, B ON  ->  expect Machine A\n" + "=" * 74)
    for m in ("A", "B"):
        if not up(ports[m]):
            start_port(ports[m])
    r1 = ask("both up", allow_cloud=False)
    ask("both up, warm", allow_cloud=False)
    rep.record("A ON, B ON -> A serves", r1["machine"] == "A", "machine=" + r1["machine"])

    print("\n" + "=" * 74 + "\n2. A OFF  ->  expect Machine B\n" + "=" * 74)
    print("  stopped A:", stop_port(ports["A"]))
    r2a = ask("first call after A died", allow_cloud=False)
    r2b = ask("next call", allow_cloud=False)
    rep.record("A OFF -> B serves the same request", r2a["machine"].endswith("B"),
               "machine=" + r2a["machine"])
    rep.record("A OFF -> B keeps serving", r2b["machine"].endswith("B"),
               "machine=" + r2b["machine"])

    print("\n" + "=" * 74 + "\n3. A OFF, B OFF  ->  expect cloud\n" + "=" * 74)
    print("  stopped B:", stop_port(ports["B"]))
    r3 = ask("both dead", allow_cloud=True)
    t0 = time.time()
    conf = providers.configured("eva_local")
    imm_ms = (time.time() - t0) * 1000
    print("  immediately after: configured(eva_local)=%s in %.2fms" % (conf, imm_ms))
    rep.record("both OFF -> local unavailable", conf is False, "configured=%s" % conf)
    rep.record("both OFF -> fast-fail, no dial", imm_ms < 50, "%.2fms" % imm_ms)
    if args.cloud:
        rep.record("both OFF -> cloud answers", bool(r3["answer"]),
                   "served=%s" % (r3["who"] or "NONE"))

    print("\n" + "=" * 74 + "\n4. Servers back, cooldown live  ->  no flapping\n" + "=" * 74)
    print("  started A:", start_port(ports["A"]), "| started B:", start_port(ports["B"]))
    r4 = ask("up again, cooldown live", allow_cloud=args.cloud)
    rep.record("cooldown live -> local still skipped", r4["local"] is False,
               "configured=%s" % r4["local"])

    cooldown = providers._eva_local_cooldown_s()
    print("\n" + "=" * 74 + "\n5. Cooldown lapses  ->  Machine A preferred again\n" + "=" * 74)
    print("  waiting %.0fs..." % (cooldown + 2))
    time.sleep(cooldown + 2)
    r5a = ask("first call after cooldown", allow_cloud=False)
    r5b = ask("steady state", allow_cloud=False)
    rep.record("after cooldown -> A preferred again", r5a["machine"] == "A",
               "machine=" + r5a["machine"])
    rep.record("recovered -> A steady", r5b["machine"] == "A" and bool(r5b["answer"]),
               "machine=" + r5b["machine"])


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lifecycle", action="store_true",
                    help="start/stop LOCAL Ollama servers and walk the whole matrix "
                         "(dev box only; needs both machines on loopback)")
    ap.add_argument("--expect", metavar="A|B|CLOUD",
                    help="observe mode: assert who serves right now")
    ap.add_argument("--cloud", action="store_true",
                    help="allow real cloud calls when local cannot answer")
    ap.add_argument("--repeat", type=int, default=1, metavar="N",
                    help="observe mode: probe N times")
    args = ap.parse_args(argv)

    if not providers._eva_local_enabled():
        print("EVA_LOCAL_ENABLED is not set: eva_local is off, so there is no "
              "local routing to verify.")
        return 1
    cands = providers.eva_local_candidates()
    if not cands:
        print("No EVA Server Local machine is configured (EVA_LOCAL_A_URL/"
              "EVA_LOCAL_A_MODEL, EVA_LOCAL_B_URL/EVA_LOCAL_B_MODEL).")
        return 1
    print("machines : %s" % ", ".join(
        "%s -> %s (%s)" % (c["machine"], c["base_url"], c["model"]) for c in cands))
    print("cooldown : %ss | connect timeout: %ss | max local tokens: %s"
          % (providers._eva_local_cooldown_s(),
             providers._eva_local_connect_timeout_s(),
             providers._eva_local_max_tokens()))

    rep = Report()
    if args.lifecycle:
        mode_lifecycle(args, rep)
    else:
        mode_observe(args, rep)
    show_telemetry()
    return rep.render()


if __name__ == "__main__":
    raise SystemExit(main())
