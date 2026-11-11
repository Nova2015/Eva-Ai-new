"""Backend LLM provider contract  JARVIS 1B.

One door to the LLM providers, replacing the backend's hand-written
provider cascade that lived in three copies (the inline chat
block, `_llm_fallback`, and `ask_groq` in app.py). It deliberately MIRRORS the
shape of eva-ml-service/model_router.py  the same names (`dispatch`,
`failover_chain`, `classify_error`, `record`, `status`, `PROVIDER_SPECS`,
`PROVIDER_ORDER`)  so the two services are recognisably one contract WITHOUT
sharing code. They are separate repos with separate deploys; a shared import
would couple them, so each keeps its own copy of the same shape.

Behaviour-preserving by construction. It changes no answer and no order:

  * PROVIDER_ORDER controls the configured cloud/local order, the exact order the old backend
    cascade already tried.
  * Model strings are the exact literals the old backend used (groq
    openai/gpt-oss-120b, openai gpt-4o-mini). Gemini is the exception: its
    literal was gemini-3.5-flash, which Google has since retired, so the pin
    that was meant to preserve behaviour instead returned MODEL_NOT_FOUND on
    every call and removed Gemini from the cascade entirely. It now reads
    GEMINI_MODEL  the variable the ML service and llm_fallback already use  and
    falls back to a model that exists. The original worry was that reading the
    env would silently UPGRADE the backend's Gemini; the realised cost of not
    reading it was a backend calling a model that is gone.
  * temperature is passed to the provider ONLY when the caller supplies it. The
    old `_llm_fallback` groq/openai calls passed none (provider default); the
    inline block passed 0.7 to groq; `ask_groq` passed 0.2. Passing a default
    where the old code passed none would change the output distribution, so a
    None temperature is omitted from the request, not defaulted.
  * Gemini is called exactly as before: generate_content([system, last_user]),
    ignoring max_tokens/temperature and the middle of the message list. A richer
    Gemini conversion is a deliberate later change, not a silent one here.

Provider SDKs are imported lazily inside each adapter, so importing this module
provider SDKs are loaded lazily only when required to be installed.
"""

import os
import ipaddress
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

__all__ = [
    "PROVIDER_SPECS", "PROVIDER_ORDER", "ERROR_CODES", "ProviderResult",
    "configured", "classify_error", "record", "status",
    "dispatch", "failover_chain", "complete",
    "eva_local_resolve", "eva_local_candidates", "eva_local_status",
    "eva_local_health", "validate_base_url",
    "set_eva_local_registry_reader",
]

#  Provider registry 
PROVIDER_SPECS: Dict[str, Dict[str, str]] = {
    "openai": {"label": "OpenAI", "env": "OPENAI_API_KEY", "model": "gpt-4o-mini"},
    
    # gemini-3.5-flash was retired by Google and now answers MODEL_NOT_FOUND, so
    # the pin that used to preserve behaviour had silently killed this leg of the
    # cascade. Operator-overridable, with a LIVE default so it works unset.
    "gemini": {"label": "Gemini", "env": "GEMINI_API_KEY",
               "model": (os.getenv("GEMINI_MODEL") or "").strip() or "gemini-2.5-flash"},
    "groq": {
    "label": "Groq",
    "env": "GROQ_API_KEY",
    "model": "openai/gpt-oss-120b",
    },
    # Local Ollama backstop (JARVIS 3): an OpenAI-compatible endpoint on your own
    # infra, independent of every cloud free-tier quota. "configured" = OLLAMA_URL
    # is set, so it is skipped cleanly when there is no host. LAST in the order.
    "local":  {"label": "Local",  "env": "OLLAMA_URL",     "model": os.getenv("OLLAMA_MODEL", "gemma3:12b")},
    # EVA Server Local (Phase 2 Step 8): the same config-driven local capability
    # eva-ml-service has, mirrored here WITHOUT shared code. Config comes from the
    # registry first (none in the backend today) then the env bootstrap
    # (EVA_LOCAL_A_URL / EVA_LOCAL_A_MODEL, and B). No cloud API key is required.
    # Deliberately NOT in PROVIDER_ORDER: it is never in the automatic cascade and
    # never the default €” reachable only via an explicit dispatch("eva_local").
    "eva_local": {"label": "EVA Server Local", "env": "EVA_LOCAL_A_URL", "model": os.getenv("EVA_LOCAL_A_MODEL", "")},
}

# The backend cascade order. Configured providers are tried in failover order
# configured on this deployment (see the Update 54 note on _llm_fallback);
# then OpenAI, then Gemini, then the Local backstop LAST €” a pure floor that
# changes nothing until the cloud providers ahead of it have all failed.
PROVIDER_ORDER: List[str] = ["groq", "openai", "gemini", "local"]

ERROR_CODES: Tuple[str, ...] = (
    "RATE_LIMITED", "AUTH", "TIMEOUT", "MODEL_NOT_FOUND", "EMPTY_RESPONSE", "ERROR",
)


@dataclass
class ProviderResult:
    text: str
    provider: str            # a provider id, or "unavailable" when all failed
    model: str
    ok: bool
    error_code: Optional[str] = None
    errors: Optional[List[str]] = None   # per-provider failure codes, admin-only


# ”€ Per-provider health (in-memory; JARVIS 2 will persist it) ”€
_health_lock = threading.Lock()
_health: Dict[str, Dict[str, Any]] = {}

# Observers notified after each provider call is recorded, with
# (provider_id, ok, error_code, latency_ms). The provider shadow (JARVIS 2A)
# registers one to persist per-provider health. Kept here rather than importing
# the shadow, so providers.py carries no storage dependency and there is no
# import cycle €” the shadow imports THIS module for the error enum, not vice
# versa.
_record_observers: List[Callable[[str, bool, Optional[str], Optional[int]], None]] = []


def add_record_observer(
        fn: Callable[[str, bool, Optional[str], Optional[int]], None]) -> None:
    """Register a callback invoked after every record(), with
    (provider_id, ok, error_code, latency_ms). Observers must not raise;
    exceptions are swallowed so telemetry can never break a provider call."""
    if fn not in _record_observers:
        _record_observers.append(fn)


#  EVA Server Local config resolution (Phase 2 Step 8) 
# Registry-first, env-bootstrap fallback  mirrors eva-ml-service's contract
# WITHOUT shared code. The backend has no registry today, so _eva_local_registry
# returns {} and the env bootstrap is used ("registry unavailable  env").
_EVA_LOCAL_ALLOWED_SCHEMES = ("http", "https")
_EVA_LOCAL_MACHINE_ENV = {
    "A": {"url": "EVA_LOCAL_A_URL", "model": "EVA_LOCAL_A_MODEL",
          "quant": "EVA_LOCAL_A_QUANT", "context": "EVA_LOCAL_A_CONTEXT"},
    "B": {"url": "EVA_LOCAL_B_URL", "model": "EVA_LOCAL_B_MODEL",
          "quant": "EVA_LOCAL_B_QUANT", "context": "EVA_LOCAL_B_CONTEXT"},
}


def _eva_local_enabled() -> bool:
    return os.getenv("EVA_LOCAL_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


# Phase 2 Step 14: the registry reader is INJECTED, not imported. The model
# registry lives in Supabase and is owned by eva-ml-service; importing a reader
# here would give this module the storage dependency it is documented not to
# have. app.py injects src/eva_local_registry.read at start-up, exactly as it
# injects the shadow observer.
_eva_local_registry_reader: Optional[Callable[[], Dict[str, Any]]] = None


def set_eva_local_registry_reader(fn: Optional[Callable[[], Dict[str, Any]]]) -> None:
    """Install (or clear, with None) the function that returns the active
    eva_local registry block. Without one the env bootstrap is authoritative."""
    global _eva_local_registry_reader
    _eva_local_registry_reader = fn


def _eva_local_registry() -> Dict[str, Any]:
    """The active eva_local registry block, or {} when there is none.

    Registry-first: whatever this returns wins over the env bootstrap in
    eva_local_resolve(). Fail-safe  no reader injected, or a reader that raises
    or returns a non-dict, degrades to {} and therefore to today's env-only
    behaviour. A registry value is NOT trusted blindly: base_url still goes
    through validate_base_url(), so a row in the database cannot reach a host
    the SSRF policy forbids."""
    fn = _eva_local_registry_reader
    if fn is None:
        return {}
    try:
        block = fn()
    except Exception:
        return {}
    return block if isinstance(block, dict) else {}


def _host_is_safe(host: str) -> bool:
    """Mirrors the Step-1 SSRF policy: literal IPs must be private/loopback;
    public and link-local/metadata (169.254.169.254) are rejected; hostnames are
    allowed (LAN names are legitimate). Not resolved here."""
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    if ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        return False
    return ip.is_private or ip.is_loopback


def validate_base_url(raw: Optional[str]) -> Optional[str]:
    """Return a normalized LAN HTTP(S) base URL, or None. Rejects non-HTTP(S)
    schemes, embedded credentials, malformed URLs, and public/link-local hosts.
    Reusable, and applied to every config-supplied eva_local base_url."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        u = urlparse(raw)
    except Exception:
        return None
    if u.scheme not in _EVA_LOCAL_ALLOWED_SCHEMES:
        return None
    if u.username or u.password:
        return None
    if not u.hostname or not _host_is_safe(u.hostname):
        return None
    return raw.rstrip("/")


def _reg_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _eva_local_machine_key(machine: str) -> str:
    """Health key for one machine, distinct from the "eva_local" provider key
    that stays the telemetry aggregate across both."""
    return "eva_local:" + machine


def eva_local_candidates() -> List[Dict[str, str]]:
    """Every configured+valid machine, Machine A first, regardless of health.

    Config only: no URL, an SSRF-rejected URL or no model means not a candidate,
    and B is never invented when it was not configured.
    """
    out: List[Dict[str, str]] = []
    reg_machines = (_eva_local_registry().get("machines") or {})
    for machine, keys in _EVA_LOCAL_MACHINE_ENV.items():
        rm = reg_machines.get(machine) or {}
        raw_url = _reg_str(rm.get("base_url")) or os.getenv(keys["url"], "").strip()
        if not raw_url:
            continue
        base_url = validate_base_url(raw_url)
        if base_url is None:
            continue                      # SSRF-invalid  do not serve from it
        model = _reg_str(rm.get("model")) or os.getenv(keys["model"], "").strip()
        if not model:
            continue
        out.append({"machine": machine, "base_url": base_url, "model": model})
    return out


def eva_local_resolve() -> Optional[Dict[str, str]]:
    """The machine that would serve right now: A preferred, B when A is
    unavailable, None when neither is.

    Health-aware, which is what makes A->B failover real rather than a label: a
    machine whose breaker is open is skipped, so a down A hands over to a healthy
    B instead of taking the whole local provider down with it, and a recovered A
    is preferred again because candidates are always ordered A first.
    """
    for cfg in eva_local_candidates():
        if not _eva_local_tripped(cfg["machine"]):
            return cfg
    return None


def eva_local_status() -> Dict[str, Any]:
    """Phase 2 Step 10  read-only EVA Server Local A/B visibility.

    Pure and side-effect free: it resolves the SAME config the serving path uses
    (registry-first, then env, via eva_local_resolve/validate_base_url) and
    reports it. It makes NO network call and performs NO health probe  the
    backend has none, so `reachable` is always None rather than guessed. It
    changes no routing and adds no failover.

    Safe metadata only: machine id, configured flag, the VALIDATED base_url, the
    configured model, and which machine would be selected. Never a key, bearer,
    prompt, answer, or any secret. A base_url rejected by the SSRF policy is
    reported as None with detail="invalid_base_url"  the unsafe value is not
    echoed back.
    """
    selected = eva_local_resolve()
    reg_machines = (_eva_local_registry().get("machines") or {})
    machines: List[Dict[str, Any]] = []
    for machine, keys in _EVA_LOCAL_MACHINE_ENV.items():
        rm = reg_machines.get(machine) or {}
        raw_url = _reg_str(rm.get("base_url")) or os.getenv(keys["url"], "").strip()
        model = _reg_str(rm.get("model")) or os.getenv(keys["model"], "").strip()
        base_url = validate_base_url(raw_url) if raw_url else None
        if not raw_url:
            detail = "unconfigured"
        elif base_url is None:
            detail = "invalid_base_url"
        elif not model:
            detail = "no_model"
        else:
            detail = "configured"
        machines.append({
            "machine": machine,
            "configured": detail == "configured",
            "detail": detail,
            "base_url": base_url,
            "model": model or None,
            "reachable": None,
            # Per-machine routing state, so "A is down and B is carrying it" is
            # distinguishable from "both are fine".
            "skipped_now": _eva_local_tripped(machine),
            "health": eva_local_health(machine),
        })
    return {
        "enabled": _eva_local_enabled(),
        "available": configured("eva_local"),
        "selected_machine": selected["machine"] if selected else None,
        "machines": machines,
        "probe": "unavailable",
        # Phase 2 Step 12: runtime outcomes of ACTUAL eva_local calls, recorded
        # by the same record() contract the cloud providers use. Reported here
        # rather than in status(), whose `live` array intentionally mirrors
        # PROVIDER_ORDER  eva_local is not in that order and has not joined it.
        "health": eva_local_health(),
    }


def eva_local_health(machine: Optional[str] = None) -> Dict[str, Any]:
    """Recorded call outcomes: one machine's when given, otherwise the aggregate
    across both. Counts, a fixed error enum and latency only  never a prompt,
    answer, URL, key or bearer. Zeroed until a call has been made."""
    now = time.time()
    key = _eva_local_machine_key(machine) if machine else "eva_local"
    with _health_lock:
        h = dict(_health.get(key, {}))
    last_ok = h.get("last_success_at")
    last_err = h.get("last_error_at")
    return {
        "requests": h.get("requests", 0),
        "failures": h.get("failures", 0),
        "last_error_code": h.get("last_error_code"),
        "last_latency_ms": h.get("last_latency_ms"),
        "last_success_seconds_ago": round(now - last_ok) if last_ok else None,
        "last_error_seconds_ago": round(now - last_err) if last_err else None,
    }


def configured(pid: str) -> bool:
    if pid == "eva_local":
        # eva_local is available only when explicitly enabled AND a machine is
        # configured+valid. With EVA_LOCAL_ENABLED unset/false it is never
        # available, so the cloud path is unchanged.
        #
        # A machine whose fast-fail breaker is open is NOT available either: it
        # is known-down, and dialling it costs a full connect timeout before the
        # cloud cascade can run. The check lives here rather than at each call
        # site because every caller asks this same question  the chat fallback,
        # the streaming branch and failover_chain  and a future caller would
        # otherwise have to remember to ask twice. `_eva_local_tripped` is
        # defined below; name resolution happens at call time.
        # eva_local_resolve() is health-aware, so this stays true while EITHER
        # machine can serve, and goes false only when every configured machine is
        # unavailable  the point at which the cloud cascade takes over.
        return _eva_local_enabled() and eva_local_resolve() is not None
    return bool(os.getenv(PROVIDER_SPECS[pid]["env"], ""))


def classify_error(exc: Exception) -> str:
    """Fixed enum for dashboards and logs  never free text from the provider.

    Same mapping as the ML service's _classify_provider_error, so a rate limit
    reads as RATE_LIMITED on both sides.
    """
    s = str(exc).lower()
    if "429" in s or "rate limit" in s or "quota" in s or "resource_exhausted" in s:
        return "RATE_LIMITED"
    if "401" in s or "403" in s or "unauthorized" in s or "permission" in s or "api key" in s:
        return "AUTH"
    if "timeout" in s or "timed out" in s or "deadline" in s:
        return "TIMEOUT"
    if "404" in s or "not found" in s or "does not exist" in s:
        return "MODEL_NOT_FOUND"
    if "empty response" in s:
        return "EMPTY_RESPONSE"
    return "ERROR"


def _record_health(pid: str, ok: bool, code: Optional[str] = None,
                   latency_ms: Optional[int] = None) -> None:
    """Write one outcome into the health snapshot WITHOUT notifying observers.

    Per-machine keys ("eva_local:A") are routing state, not provider telemetry:
    the shadow's provider vocabulary is a fixed enum that would drop them, so
    they must not be announced as though a new provider had appeared.
    """
    try:
        with _health_lock:
            h = _health.setdefault(pid, {
                "requests": 0, "failures": 0, "last_error_code": None,
                "last_error_at": None, "last_success_at": None, "last_latency_ms": None,
            })
            h["requests"] += 1
            if latency_ms is not None:
                h["last_latency_ms"] = latency_ms
            if ok:
                h["last_success_at"] = time.time()
            else:
                h["failures"] += 1
                h["last_error_code"] = code
                h["last_error_at"] = time.time()
    except Exception:
        pass


def record(pid: str, ok: bool, code: Optional[str] = None,
           latency_ms: Optional[int] = None) -> None:
    """Fold one provider call into the health snapshot and tell the observers.
    Never raises."""
    _record_health(pid, ok, code, latency_ms)
    # Notify observers OUTSIDE the health lock so a slow/faulty observer cannot
    # stall the next provider call, and a raising one cannot corrupt the count.
    for observer in list(_record_observers):
        try:
            observer(pid, ok, code, latency_ms)
        except Exception:
            pass


def status() -> List[Dict[str, Any]]:
    """Live per-provider status. Mirrors the ML service's provider_status: a
    RATE_LIMITED/error state decays 10 minutes after the last failure, so a
    provider that recovered is not shown broken forever."""
    now = time.time()
    with _health_lock:
        snap = {k: dict(v) for k, v in _health.items()}
    out = []
    for pid in PROVIDER_ORDER:
        spec = PROVIDER_SPECS[pid]
        h = snap.get(pid, {})
        last_err_at = h.get("last_error_at")
        recent_failure = last_err_at is not None and (now - last_err_at) < 600
        # >= (not >) so a success clears a prior error even when both land on the
        # same coarse time.time() tick (e.g. two rapid calls on Windows' ~15ms
        # clock); a failure-only provider still has last_success_at 0 < last_err_at.
        succeeded_since = (h.get("last_success_at") or 0) >= (last_err_at or 0)
        if not configured(pid):
            st, detail = "no_key", f"{spec['env']} not configured"
        elif recent_failure and not succeeded_since:
            code = h.get("last_error_code") or "ERROR"
            st = "rate_limited" if code == "RATE_LIMITED" else "error"
            detail = code
        else:
            st, detail = "healthy", "ok"
        out.append({
            "id": pid, "label": spec["label"], "model": spec["model"],
            "status": st, "detail": detail,
            "requests": h.get("requests", 0), "failures": h.get("failures", 0),
            "last_error_code": h.get("last_error_code"),
            "last_latency_ms": h.get("last_latency_ms"),
        })
    return out


#  Provider adapters (lazy SDK imports; blocking, as the old code was) 
def _messages_with_optional_temperature(model: str, messages: List[Dict[str, str]],
                                        max_tokens: int, temperature: Optional[float]) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if temperature is not None:
        kwargs["temperature"] = temperature
    return kwargs


def _call_groq(messages: List[Dict[str, str]], model: str,
               max_tokens: int, temperature: Optional[float]) -> str:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    from groq import Groq

    client = Groq(api_key=api_key)
    resp = client.chat.completions.create(
        **_messages_with_optional_temperature(
            model, messages, max_tokens, temperature
        )
    )
    return resp.choices[0].message.content or ""

def _call_openai(messages: List[Dict[str, str]], model: str,
                 max_tokens: int, temperature: Optional[float]) -> str:
    import openai
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
    resp = client.chat.completions.create(
        **_messages_with_optional_temperature(model, messages, max_tokens, temperature))
    return resp.choices[0].message.content or ""


def _call_gemini(messages: List[Dict[str, str]], model: str,
                 max_tokens: int, temperature: Optional[float]) -> str:
    # Preserves the old backend call exactly: system + last user only, no
    # history, no generation_config. max_tokens/temperature are ignored, as
    # they were before.
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))
    gm = genai.GenerativeModel(model)
    resp = gm.generate_content([messages[0]["content"], messages[-1]["content"]])
    return resp.text or ""


def _call_local(messages: List[Dict[str, str]], model: str,
                max_tokens: int, temperature: Optional[float]) -> str:
    # Local Ollama via its OpenAI-compatible API at {OLLAMA_URL}/v1. The openai
    # SDK speaks that contract with a base_url override; Ollama ignores the key,
    # so any non-empty value satisfies the header.
    import openai
    base = os.getenv("OLLAMA_URL", "").rstrip("/")
    client = openai.OpenAI(api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
                           base_url=f"{base}/v1")
    resp = client.chat.completions.create(
        **_messages_with_optional_temperature(model, messages, max_tokens, temperature))
    return resp.choices[0].message.content or ""


def _call_eva_local(messages: List[Dict[str, str]], model: str,
                    max_tokens: int, temperature: Optional[float]) -> str:
    # EVA Server Local via its OpenAI-compatible API. base_url and model are
    # resolved from config at CALL time (registry-first, then env); the config
    # model is authoritative. The base_url already includes any runtime path
    # prefix (e.g. /v1)  no runtime-specific path is assumed. The endpoint
    # ignores the bearer, so a static non-secret satisfies the header: NO cloud
    # API key is required or sent.
    if not _eva_local_enabled():
        raise RuntimeError("eva_local is disabled (EVA_LOCAL_ENABLED)")
    max_tokens = min(max_tokens, _eva_local_max_tokens())
    # Try each machine that is not already known-down, Machine A first. A failure
    # belongs to that machine, not to the provider, so B still gets its turn in
    # the SAME request; only when every machine has failed does the caller fall
    # through to the cloud cascade.
    errors: List[str] = []
    for cfg in eva_local_candidates():
        if _eva_local_tripped(cfg["machine"]):
            continue
        print(f"[EVA LOCAL DEBUG] trying machine={cfg.get('machine')} base_url={cfg.get('base_url')!r} model={cfg.get('model')!r}")
        try:
            return _call_eva_local_machine(cfg, messages, max_tokens, temperature)
        except Exception as exc:
            print(f"[EVA LOCAL RAW ERROR - OUTER] {type(exc).__name__}: {exc}")
            errors.append(cfg["machine"] + ": " + classify_error(exc))
    if errors:
        raise RuntimeError("eva_local all machines failed: " + "; ".join(errors))
    raise RuntimeError("eva_local is not configured (registry or env)")


def _call_eva_local_machine(cfg: Dict[str, str], messages: List[Dict[str, str]],
                            max_tokens: int, temperature: Optional[float]) -> str:
    """One machine, one attempt. Records the outcome twice: against the machine
    (routing state, drives its breaker) and against "eva_local" (the provider
    telemetry the shadow already understands)."""
    machine_key = _eva_local_machine_key(cfg["machine"])
    client = _eva_local_client(cfg["base_url"])
    # Phase 2 Step 12: record the CALL outcome through the same contract every
    # cloud provider uses (record + classify_error, fixed enum). Recorded here
    # rather than in complete(), because eva_local is deliberately absent from
    # PROVIDER_ORDER and so never walks the failover chain that records for the
    # others  which left local calls with no telemetry at all. The config
    # guards above raise BEFORE this point on purpose: a provider that was never
    # contacted must not count as a failed request.
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            **_messages_with_optional_temperature(cfg["model"], messages, max_tokens, temperature))
    except Exception as exc:
        print(f"[EVA LOCAL RAW ERROR] {type(exc).__name__}: {exc}")
        _code = classify_error(exc)
        _ms = int((time.time() - t0) * 1000)
        _record_health(machine_key, ok=False, code=_code, latency_ms=_ms)
        record("eva_local", ok=False, code=_code, latency_ms=_ms)
        raise
    latency_ms = int((time.time() - t0) * 1000)
    text = resp.choices[0].message.content or ""
    # An empty answer counts as a failure, the same rule complete() applies to
    # every other provider.
    if text.strip():
        _record_health(machine_key, ok=True, latency_ms=latency_ms)
        record("eva_local", ok=True, latency_ms=latency_ms)
    else:
        _record_health(machine_key, ok=False, code="EMPTY_RESPONSE", latency_ms=latency_ms)
        record("eva_local", ok=False, code="EMPTY_RESPONSE", latency_ms=latency_ms)
    return text


def stream_eva_local(messages: List[Dict[str, str]], *, max_tokens: int = 1024,
                     temperature: Optional[float] = None):
    """Phase 2 Step 9  stream from the configured EVA Server Local machine over
    the OpenAI-compatible SSE contract (stream=true). Yields assistant content
    deltas (strings); the caller frames them into the app's existing SSE events.

    Config-driven exactly like _call_eva_local (registry-first  env; SSRF via
    eva_local_resolve; static non-secret bearer, NO cloud API key). Targets ONLY
    the resolved primary machine  there is NO A->B failover and NO cloud
    fallback here: a failure raises so the caller can surface it through the
    existing streaming error event.
    """
    if not _eva_local_enabled():
        raise RuntimeError("eva_local is disabled (EVA_LOCAL_ENABLED)")
    cfg = eva_local_resolve()          # health-aware: A, else B, else None
    if cfg is None:
        raise RuntimeError("eva_local is not configured (registry or env)")
    machine_key = _eva_local_machine_key(cfg["machine"])
    max_tokens = min(max_tokens, _eva_local_max_tokens())
    client = _eva_local_client(cfg["base_url"])
    kwargs = _messages_with_optional_temperature(cfg["model"], messages, max_tokens, temperature)
    kwargs["stream"] = True
    # Step 12: one health record per stream  success when it completes having
    # produced content, EMPTY_RESPONSE when it completes having produced none,
    # and a classify_error code when it raises (before or mid-stream). Failure
    # is still re-raised, so the caller's error event and the no-failover /
    # no-cloud-fallback rule are unchanged.
    t0 = time.time()
    produced = False
    try:
        stream = client.chat.completions.create(**kwargs)
        for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue                   # role/finish/keepalive frames carry no content
            delta = getattr(choices[0], "delta", None)
            content = getattr(delta, "content", None) if delta is not None else None
            if content:
                produced = True
                yield content
    except Exception as exc:
        print(f"[EVA LOCAL RAW ERROR] {type(exc).__name__}: {exc}")
        _code = classify_error(exc)
        _ms = int((time.time() - t0) * 1000)
        _record_health(machine_key, ok=False, code=_code, latency_ms=_ms)
        record("eva_local", ok=False, code=_code, latency_ms=_ms)
        raise
    latency_ms = int((time.time() - t0) * 1000)
    if produced:
        _record_health(machine_key, ok=True, latency_ms=latency_ms)
        record("eva_local", ok=True, latency_ms=latency_ms)
    else:
        _record_health(machine_key, ok=False, code="EMPTY_RESPONSE", latency_ms=latency_ms)
        record("eva_local", ok=False, code="EMPTY_RESPONSE", latency_ms=latency_ms)



_ADAPTERS: Dict[str, Callable[[List[Dict[str, str]], str, int, Optional[float]], str]] = {
    "groq": _call_groq,
    "gemini": _call_gemini,
    "openai": _call_openai,
    "local": _call_local,
    "eva_local": _call_eva_local,
}



#  Dispatch / failover / cascade 
def dispatch(pid: str, messages: List[Dict[str, str]], *,
             model: Optional[str] = None, max_tokens: int = 1024,
             temperature: Optional[float] = None) -> str:
    """Call ONE provider. Pure like the ML service's _dispatch: it raises on a
    provider error and returns the text (possibly "") on success. It does not
    record health  the caller that owns the loop does that."""
    if pid not in _ADAPTERS:
        raise RuntimeError(f"unknown provider {pid}")
    model = model or PROVIDER_SPECS[pid]["model"]
    return _ADAPTERS[pid](messages, model, max_tokens, temperature)


#  EVA Server Local fast-fail breaker 
# A machine that is down costs a full connect timeout on EVERY request before
# the cloud cascade runs  the SDK retries a refused connection, measured at
# ~7.9s. This skips local while it is known-down, using the health record()
# already writes: no second state store, no background poller, and no health
# ping (the next real request after the cooldown IS the probe).
#
# Availability failures only. EMPTY_RESPONSE means the machine answered and is
# therefore up  merely unhelpful  and must not cost it its place in the chain.
_EVA_LOCAL_TRIP_CODES = frozenset({"ERROR", "TIMEOUT", "MODEL_NOT_FOUND", "AUTH"})

# Deliberately NOT status()'s 600s window: that decay is tuned for a dashboard,
# where showing a recovered provider as broken for ten minutes is merely untidy.
# Routing on it would ignore a machine that came back within seconds. Matches
# eva-ml-service's EVA_LOCAL_HEALTH_COOLDOWN_S so one value tunes both services.
_EVA_LOCAL_COOLDOWN_S = 30.0


# A local 3B model generates at ~60 tok/s, so an unbounded 1024-token reply is
# ~17s of pure generation. The chat path's ceiling was written for cloud models
# that stream far faster; local gets its own, lower one. A caller asking for
# fewer tokens still gets fewer  this is a cap, not a target.
_EVA_LOCAL_MAX_TOKENS = 512


def _eva_local_max_tokens() -> int:
    raw = (os.getenv("EVA_LOCAL_MAX_TOKENS", "") or "").strip()
    if not raw:
        return _EVA_LOCAL_MAX_TOKENS
    try:
        return max(1, int(raw))
    except ValueError:
        return _EVA_LOCAL_MAX_TOKENS


# A machine that is DOWN must cost little to discover. The SDK default is a
# 600s request timeout with 2 internal retries, so one dead machine burned ~10s
# of connect+backoff before the next one was even tried  paid again on every
# half-open probe. Connect is the only phase that should be short: generation
# legitimately takes minutes, so the request timeout stays at the SDK default.
# Internal retries are disabled outright  A -> B -> cloud IS the retry policy,
# and retrying inside one dead machine only delays reaching the next.
_EVA_LOCAL_CONNECT_TIMEOUT_S = 2.0
_EVA_LOCAL_REQUEST_TIMEOUT_S = 600.0


def _eva_local_connect_timeout_s() -> float:
    raw = (os.getenv("EVA_LOCAL_CONNECT_TIMEOUT_S", "") or "").strip()
    if not raw:
        return _EVA_LOCAL_CONNECT_TIMEOUT_S
    try:
        return max(0.05, float(raw))
    except ValueError:
        return _EVA_LOCAL_CONNECT_TIMEOUT_S


def _eva_local_request_timeout_s() -> float:
    raw = (os.getenv("EVA_LOCAL_REQUEST_TIMEOUT_S", "") or "").strip()
    if not raw:
        return _EVA_LOCAL_REQUEST_TIMEOUT_S
    try:
        return max(1.0, float(raw))
    except ValueError:
        return _EVA_LOCAL_REQUEST_TIMEOUT_S


def _eva_local_client(base_url: str):
    """The OpenAI-compatible client for one local machine. One factory, so the
    blocking and streaming paths cannot drift apart on timeouts."""
    import openai
    kwargs: Dict[str, Any] = {"api_key": "eva-local", "base_url": base_url,
                              "max_retries": 0}
    try:
        import httpx
        kwargs["timeout"] = httpx.Timeout(_eva_local_request_timeout_s(),
                                          connect=_eva_local_connect_timeout_s())
    except Exception:
        # httpx ships with the openai SDK; if it is somehow absent, keep the
        # SDK's own timeout rather than clamping generation to the connect budget.
        pass
    return openai.OpenAI(**kwargs)


def _eva_local_cooldown_s() -> float:
    raw = (os.getenv("EVA_LOCAL_HEALTH_COOLDOWN_S", "") or "").strip()
    if not raw:
        return _EVA_LOCAL_COOLDOWN_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _EVA_LOCAL_COOLDOWN_S


def _eva_local_tripped(machine: Optional[str] = None) -> bool:
    """True while a machine should be skipped: its last call failed on
    availability, nothing has succeeded since, and the cooldown has not lapsed.

    `machine` selects one machine's state ("A"/"B"); without it the aggregate
    "eva_local" record is read, for callers asking about the provider as a whole.

    Three states, no stored machine: CLOSED (never failed, or succeeded since),
    OPEN (within the cooldown  skipped), HALF-OPEN (cooldown lapsed  this
    returns False, so the next real request is the trial; its outcome closes or
    re-opens the breaker through the same record() call it already makes).
    """
    key = _eva_local_machine_key(machine) if machine else "eva_local"
    with _health_lock:
        h = dict(_health.get(key, {}))
    last_err_at = h.get("last_error_at")
    if not last_err_at:
        return False                                    # never failed
    if h.get("last_error_code") not in _EVA_LOCAL_TRIP_CODES:
        return False                                    # answered, just not usefully
    # >= not >: two calls can land on the same coarse clock tick, and a success
    # that ties with the failure means it recovered.
    if (h.get("last_success_at") or 0) >= last_err_at:
        return False                                    # recovered since
    return (time.time() - last_err_at) < _eva_local_cooldown_s()


def failover_chain(order: Optional[List[str]] = None) -> List[Tuple[str, str]]:
    """Configured providers, in preference order, as (id, model) pairs. Skips
    any provider with no API key  the old cascade guarded each call with an
    `if <key>:` for the same reason.

    EVA Server Local goes FIRST when it is explicitly enabled and a machine
    actually resolves. It is still absent from PROVIDER_ORDER and is prepended
    here at call time, so with EVA_LOCAL_ENABLED unset this returns exactly the
    old cloud chain  the cloud cascade remains the guaranteed floor, and no
    external provider ever becomes mandatory. An explicit `order` is honoured
    verbatim, so a caller asking for a specific cascade still gets one.

    The model label comes from the resolved config rather than PROVIDER_SPECS,
    which reads EVA_LOCAL_A_MODEL once at import and can be stale or empty.
    """
    chain: List[Tuple[str, str]] = []
    if order is None and configured("eva_local"):
        local = eva_local_resolve()
        if local:
            chain.append(("eva_local", local["model"]))
    for pid in (order or PROVIDER_ORDER):
        if pid in PROVIDER_SPECS and configured(pid):
            chain.append((pid, PROVIDER_SPECS[pid]["model"]))
    return chain


def complete(messages: List[Dict[str, str]], *, max_tokens: int = 1024,
             temperature: Optional[float] = None,
             order: Optional[List[str]] = None) -> ProviderResult:
    """Walk the failover chain and return the first non-empty answer.

    An empty response counts as a failure and moves to the next provider  the
    same rule the ML service's route_and_call uses, and the same effect the old
    backend cascade had (an empty provider answer falls through to the next provider). Records
    per-provider health as it goes. Returns a provider="unavailable" result when
    every configured provider failed, exactly as the old cascade returned "".
    """
    errors: List[str] = []
    for pid, model in failover_chain(order):
        t0 = time.time()
        try:
            text = dispatch(pid, messages, model=model,
                            max_tokens=max_tokens, temperature=temperature)
        except Exception as exc:
            code = classify_error(exc)
            record(pid, ok=False, code=code, latency_ms=int((time.time() - t0) * 1000))
            errors.append(f"{pid}: {code}")
            continue
        latency = int((time.time() - t0) * 1000)
        if (text or "").strip():
            record(pid, ok=True, latency_ms=latency)
            return ProviderResult(text=text, provider=pid, model=model, ok=True,
                                  error_code=None, errors=errors or None)
        record(pid, ok=False, code="EMPTY_RESPONSE", latency_ms=latency)
        errors.append(f"{pid}: EMPTY_RESPONSE")
    return ProviderResult(text="", provider="unavailable", model="", ok=False,
                          error_code="ALL_FAILED", errors=errors or None)
