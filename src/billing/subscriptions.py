from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from billing.billing_store import DEFAULT_ORG_ID, change_subscription, get_subscription, record_usage
from billing.payments import payment_placeholder
from billing.usage_limits import limits_for_plan
from billing.webhooks import record_webhook
from eva_phase_common import now_iso, read_state, write_state


router = APIRouter(tags=["billing"])


@router.post("/billing/subscribe")
def subscribe(payload: Dict[str, Any]):
    plan_id = (payload.get("plan_id") or payload.get("plan") or "pro").lower()
    organization_id = payload.get("organization_id", DEFAULT_ORG_ID)
    try:
        state = change_subscription(organization_id=organization_id, plan_id=plan_id, actor_user_id=payload.get("user_id", "user_001"))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True, **state, "limits": limits_for_plan(plan_id), "payment": payment_placeholder()}


@router.post("/billing/cancel")
def cancel_subscription(payload: Dict[str, Any]):
    organization_id = payload.get("organization_id", DEFAULT_ORG_ID)
    state = read_state("billing_cancellations", {"items": []})
    item = {"organization_id": organization_id, "requested_by": payload.get("user_id", "user_001"), "created_at": now_iso(), "status": "scheduled"}
    state.setdefault("items", []).insert(0, item)
    write_state("billing_cancellations", state)
    record_usage(organization_id=organization_id, user_id=payload.get("user_id", "user_001"), feature="subscription_cancel_requested", quantity=1)
    return {"ok": True, "cancellation": item, **get_subscription(organization_id)}


@router.post("/billing/webhook")
def billing_webhook(payload: Dict[str, Any]):
    return {"ok": True, "event": record_webhook(payload)}
