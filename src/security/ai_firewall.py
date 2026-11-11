from typing import Any, Dict, Optional

# NOTE: `from ipaddress import ip_address` was previously imported here and
# never used. It also collided by name with the local `ip_address` variable
# inside inspect_request(), which is the kind of shadowing that produces a
# confusing NameError years later. Removed.

from src.security_config import SECURITY_CONFIG
from src.security.prompt_guard import validate_prompt
from src.security.rag_guard import validate_document
from src.security.output_guard import validate_output
from src.security.threat_detector import calculate_threat_score
from src.security.security_logger import log_security_event
from src.security.pii_detector import detect_pii
from src.security.hallucination_detector import detect_hallucination
from src.security.vector_db_guard import validate_vector_query
from src.security.secure_memory import SecureMemory
from src.security.audit_monitor import AuditMonitor
from src.security.model_router_security import validate_model_access
from src.security.rag_policy_engine import validate_rag_policy
from src.security.agent_isolation import AgentIsolation
from src.security.realtime_threat_monitor import RealtimeThreatMonitor
from src.security.jwt_guard import JWTGuard
from src.security.zero_trust_security import ZeroTrustSecurity
from src.security.encryption_guard import EncryptionGuard
from src.security.session_guard import SessionGuard
from src.security.compliance_guard import ComplianceGuard
from src.security.behavior_analyzer import BehaviorAnalyzer
from src.security.threat_intelligence import ThreatIntelligence
from src.security.incident_response import IncidentResponse
from src.security.security_store import SecurityStore

# ── The firewall verdict contract (Fix 1) ────────────────────────────────
#
# Every inspect_* method returns exactly these four keys, always present:
#
#   allowed  bool          the ONLY field callers may branch on
#   message  str           human-readable, for logs and UI
#   types    list[str]     finding codes that fired (see FINDING_*)
#   details  dict          diagnostics; never branch on this
#
# Previously callers read "blocked" and "threat_level", which this class
# never returned — so `blocked = fw.get("blocked", False)` was always False
# and the firewall's verdict was silently discarded. One shape, one field to
# branch on, so that cannot recur.

FINDING_SESSION = "SESSION"
FINDING_COMPLIANCE = "COMPLIANCE"
FINDING_BEHAVIOR = "BEHAVIOR"
FINDING_THREAT_INTEL = "THREAT_INTEL"
FINDING_IP_BLOCKED = "IP_BLOCKED"
FINDING_RATE_LIMIT = "RATE_LIMIT"
FINDING_PROMPT_INJECTION = "PROMPT_INJECTION"
FINDING_VECTOR_QUERY = "VECTOR_QUERY"
FINDING_RAG_POLICY = "RAG_POLICY"
FINDING_AGENT = "AGENT"
FINDING_TOKEN = "TOKEN"
FINDING_HALLUCINATION = "HALLUCINATION"
# PII findings use the detector's own type names (EMAIL, PHONE, AADHAAR,
# CREDIT_CARD, IP_ADDRESS, API_KEY, AWS_KEY) rather than a generic "PII", so
# the UI can say what kind was seen without exposing the matched value.


def verdict(allowed: bool, message: str, types=None, details=None) -> Dict[str, Any]:
    """Build a firewall verdict. The only way results should be constructed."""
    return {
        "allowed": bool(allowed),
        "message": str(message),
        "types": list(types or []),
        "details": dict(details or {}),
    }


class AIFirewall:

    def __init__(self):

        self.firewall_name = "Enterprise AI Firewall"

        self.secure_memory = SecureMemory()

        self.audit_monitor = AuditMonitor()

        self.agent_security = AgentIsolation()

        self.threat_monitor = RealtimeThreatMonitor()
        
        self.jwt_guard = JWTGuard()

        self.zero_trust = ZeroTrustSecurity()

        self.encryption_guard = EncryptionGuard()

        self.session_guard = SessionGuard()

        self.compliance_guard = ComplianceGuard()

        self.behavior_analyzer = BehaviorAnalyzer()

        self.threat_intel = ThreatIntelligence()

        self.incident_response = IncidentResponse()

        self.security_store = SecurityStore()


    # IDENTITY
    def verify_identity(
            
        self,
        username,
        role
    ):

        allowed_users = {

            "admin": "super_admin",

            "user1": "editor",

            "user2": "viewer"
        }

        if username in allowed_users and allowed_users[username] == role:

            return {

                "allowed": True

            }

        return {

            "allowed": False,

            "message": "Unauthorized user or role"
        }
    
    # REQUEST
    def inspect_request(

        self,
        user_prompt: str,
        rag_content: Optional[str] = None,
        user_id: Optional[str] = None,
        client_ip: Optional[str] = None,
        document_name: Optional[str] = None

    ) -> Dict[str, Any]:
        """
        Inspect an inbound request.

        Fix 0: user_id, client_ip and document_name are now supplied by the
        caller. Previously these were hardcoded ("public_user", "127.0.0.1",
        "document.pdf"), which meant every user shared one rate-limit bucket,
        one session and one agent context — so a limit tripped by anyone
        applied to everyone.

        Callers that omit them keep working; the request is then treated as
        an unidentified caller rather than being silently attributed to a
        shared identity.
        """

        if not self.is_enabled("firewall_enabled"):

            return verdict(True, "Firewall disabled")

        # Real caller identity, falling back to an explicit "unknown" rather
        # than a shared constant.
        user_ref = str(user_id) if user_id else "unidentified_user"
        ip_address = str(client_ip) if client_ip else "unknown"
        session_id = f"session::{user_ref}"

        self.session_guard.create_session(

            user_ref,

            session_id
        )

        session_result = self.session_guard.validate_session(
            session_id
        )

        if not session_result["valid"]:

            return verdict(False, "Invalid session", [FINDING_SESSION])

        encrypted_prompt = self.encryption_guard.encrypt_data(
            user_prompt
        )

        decrypted_prompt = self.encryption_guard.decrypt_data(
            encrypted_prompt
        )

        compliance_result = self.compliance_guard.check_compliance(
            decrypted_prompt
        )

        if not compliance_result["compliant"]:

            return verdict(
                False,
                "Compliance violation",
                [FINDING_COMPLIANCE],
                compliance_result,
            )

        user_prompt = decrypted_prompt

        self.behavior_analyzer.track_activity(

            user_ref,

            "normal_chat_request"
        )

        behavior_result = self.behavior_analyzer.analyze_behavior(
            user_ref
        )

        if not behavior_result["safe"]:

            return verdict(
                False,
                "Suspicious user behavior detected",
                [FINDING_BEHAVIOR],
                behavior_result,
            )

        intel_result = self.threat_intel.analyze_threat(
            user_prompt
        )

        if not intel_result["safe"]:

            self.incident_response.create_incident(

                "Threat Intelligence Match",

                "CRITICAL",

                "Blocked request matched known threat intelligence"
            )

            return verdict(
                False,
                "Threat intelligence blocked request",
                [FINDING_THREAT_INTEL],
                intel_result,
            )

        # ── Zero Trust checks removed from the request path (Fix 0) ──────
        #
        # verify_identity("admin", "super_admin"), verify_device(
        # "AI_SERVER_001") and verify_location("India") were called with
        # hardcoded literals on every request. None of them read anything
        # about the actual caller, and all three always returned allowed,
        # so they could only ever fail for reasons unrelated to any user —
        # and would then have failed for every user simultaneously.
        #
        # ZeroTrustSecurity is still constructed and available. These belong
        # at authentication time with real identity, device and geo signals,
        # not in the per-message path. Recover from git history when there is
        # real data to feed them.

        # BLOCKED IP
        if self.threat_monitor.is_blocked(
            ip_address
        ):

            return verdict(False, "IP blocked", [FINDING_IP_BLOCKED])

        # RATE LIMIT
        # Sliding window, per real client IP. See realtime_threat_monitor:
        # this no longer permanently blocks on trip.
        if self.is_enabled("rate_limit"):

            rate_result = self.threat_monitor.check_rate_limit(
                ip_address,
                limit=SECURITY_CONFIG.get("MAX_REQUESTS_PER_MINUTE", 20),
                window_seconds=60,
            )

            if not rate_result["allowed"]:

                return verdict(
                    False,
                    "Too many requests",
                    [FINDING_RATE_LIMIT],
                    rate_result,
                )

        # MEMORY
        if self.is_enabled("secure_memory"):

            self.secure_memory.save(

                user_ref,

                user_prompt
            )

        # PROMPT
        if self.is_enabled("prompt_guard"):

            prompt_result = validate_prompt(
                user_prompt
            )

        else:

            prompt_result = {
                "blocked": False,
                "threat_score": 0
            }

        # RAG
        rag_result = None

        if rag_content and self.is_enabled("rag_guard"):

            rag_result = validate_document(
                rag_content
            )

        # PII
       
        if self.is_enabled("pii_detection"):

            pii_result = detect_pii(
                user_prompt
            )

            if pii_result["pii_detected"]:

                self.security_store.add_threat(
                    "PII Detected",
                    "HIGH",
                    ip_address,
                    True,
                    pii_result
                )

                self.security_store.add_incident(
                    "Sensitive Data Detected",
                    "HIGH",
                    "User prompt contained sensitive personal data",
                    "OPEN",
                    pii_result
                )

                # Report WHICH kinds of PII fired, never the matched values.
                # detected_items entries look like {"type": "EMAIL",
                # "matches": [...]}; only the type name crosses this boundary,
                # so the verdict can be logged and surfaced in the UI without
                # leaking the data the detector just found.
                pii_types = [
                    item.get("type")
                    for item in pii_result.get("detected_items", [])
                    if item.get("type")
                ]

                return verdict(
                    False,
                    "Sensitive data detected",
                    pii_types,
                    {"severity": pii_result.get("severity")},
                )

        # MODEL SECURITY — removed from the request path (Fix 0)
        #
        # This called validate_model_access("claude") on every request. The
        # model is not chosen until routing, several steps later, and this
        # deployment does not use Claude at all — so the check validated a
        # model that was never going to be called. validate_model_access is
        # still imported and belongs at the point of model selection in the
        # router, where the real model id is known.

        # VECTOR
        if self.is_enabled("vector_guard"):

            vector_result = validate_vector_query(
                user_prompt
            )

            if not vector_result["allowed"]:

                return verdict(
                    False, "Blocked vector query", [FINDING_VECTOR_QUERY]
                )

        # RAG POLICY
        # Only meaningful when an actual document is in play. Previously this
        # passed the literal "document.pdf" on every request, including ones
        # with no document at all.
        if document_name:

            rag_policy = validate_rag_policy(

                document_name,

                user_prompt
            )

            if not rag_policy["allowed"]:

                return verdict(
                    False,
                    "RAG violation",
                    [FINDING_RAG_POLICY],
                    {"document": document_name},
                )

        # AGENT
        agent_session_id = f"agent::{user_ref}"

        self.agent_security.create_session(

            agent_session_id,

            user_ref
        )

        agent_result = self.agent_security.validate_access(

            agent_session_id,

            user_ref
        )

        if not agent_result["allowed"]:

            return verdict(False, "Agent blocked", [FINDING_AGENT])

        # THREAT
        threat_result = calculate_threat_score(

            prompt_result,

            rag_result,

            None
        )

        if threat_result["blocked"]:

            self.threat_monitor.log_threat(

                ip_address,

                "Prompt Attack",

                "CRITICAL"
            )

            self.incident_response.create_incident(

                "AI Threat",

                "CRITICAL",

                "Blocked malicious AI request"
            )

            return verdict(
                False,
                "Threat detected",
                [FINDING_PROMPT_INJECTION],
                {
                    "threat_score": threat_result.get("threat_score"),
                    "patterns": (prompt_result or {}).get(
                        "detected_patterns", []
                    ),
                },
            )

        # GENERATE TOKEN
        token = self.jwt_guard.generate_token(
            user_ref
        )

        token_result = self.jwt_guard.verify_token(
            token
        )

        if not token_result["valid"]:

            return verdict(False, "Invalid JWT token", [FINDING_TOKEN])

        return verdict(True, "Request approved")

    # RESPONSE
    def inspect_response(

        self,
        ai_response: str,
        client_ip: Optional[str] = None

    ) -> Dict[str, Any]:
        """
        Inspect an outbound response. Same verdict contract as
        inspect_request: allowed / message / types / details, plus a
        "response" key carrying the sanitised text when allowed.
        """

        output_result = validate_output(
            ai_response
        )

        if self.is_enabled("hallucination_detection"):

            hallucination_result = detect_hallucination(
                ai_response
            )

            if hallucination_result["hallucination_detected"]:

                self.security_store.add_threat(
                    "Hallucination Detected",
                    "MEDIUM",
                    str(client_ip) if client_ip else "unknown",
                    True,
                    hallucination_result
                )

                self.security_store.add_incident(
                    "AI Hallucination Detected",
                    "MEDIUM",
                    "AI response contained suspicious unsupported claim",
                    "OPEN",
                    hallucination_result
                )

                result = verdict(
                    False,
                    "Hallucination detected",
                    [FINDING_HALLUCINATION],
                    {"severity": hallucination_result.get("severity")},
                )
                result["response"] = ""
                return result

        result = verdict(True, "Response approved")
        result["response"] = output_result["safe_response"]
        return result
    
    def is_enabled(self, key):

        setting = self.security_store.get_setting(key)

        if setting is None:

            return True

        if isinstance(setting, dict):

            return bool(setting.get("value", True))

        if isinstance(setting, bool):

            return setting

        if isinstance(setting, str):

            return setting.lower() == "true"

        return bool(setting)
