"""The Business Knowledge Base: what the AI is allowed to say about a business."""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BusinessKnowledge, Tenant
from app.services.agent.safety import HEALTH_PROHIBITED_DEFAULTS, is_health

MAX_ITEMS = 40


def get_row(db: Session, tenant: Tenant, *, create: bool = True) -> BusinessKnowledge | None:
    row = db.scalar(select(BusinessKnowledge).where(BusinessKnowledge.tenant_id == tenant.id))
    if row is None and create:
        health = is_health(tenant.category)
        row = BusinessKnowledge(tenant_id=tenant.id, safety_profile="health" if health else "general",
                                prohibited_claims=list(HEALTH_PROHIBITED_DEFAULTS) if health else [],
                                offers=[], faqs=[], approved_claims=[])
        db.add(row)
        db.flush()
    return row


def context(db: Session, tenant: Tenant) -> dict:
    """Everything the AI may use, as plain data. Description and services come from the shared review context (one source of truth)."""
    row = get_row(db, tenant)
    rc = tenant.review_context or {}
    return {
        "business": tenant.name, "category": tenant.category, "language": tenant.language,
        "description": rc.get("description") or "", "services": list(rc.get("services") or []),
        "offers": list(row.offers or []), "hours": row.hours or "", "faqs": list(row.faqs or []),
        "brand_voice": row.brand_voice or tenant.brand_tone or "", "approved_claims": list(row.approved_claims or []),
        "prohibited_claims": list(row.prohibited_claims or []), "safety_profile": row.safety_profile,
        "instructions": tenant.ai_instructions or "",
    }


def completeness(kb: dict) -> dict:
    """What is missing for the AI to write well. Health businesses also need hours so replies can point people to them."""
    missing = []
    if not kb["description"].strip():
        missing.append("description")
    if not kb["services"]:
        missing.append("services")
    if not kb["brand_voice"].strip():
        missing.append("brand voice")
    return {"missing": missing, "complete": not missing}


def render(kb: dict) -> str:
    """The grounding block placed in every prompt. Only facts the owner entered appear here."""
    lines = [f"BUSINESS FACTS (the ONLY facts you may state about this business):", f"- Name: {kb['business']}"]
    if kb["category"]:
        lines.append(f"- Category: {kb['category']}")
    if kb["description"]:
        lines.append(f"- About: {kb['description']}")
    if kb["services"]:
        lines.append("- Services: " + "; ".join(kb["services"]))
    if kb["hours"]:
        lines.append(f"- Opening hours: {kb['hours']}")
    if kb["offers"]:
        lines.append("- Verified prices and offers (use exactly as written, never change or add any):")
        for o in kb["offers"]:
            price = f" — ₹{o['price_inr']}" if o.get("price_inr") not in (None, "") else ""
            valid = f" (valid until {o['valid_until']})" if o.get("valid_until") else ""
            lines.append(f"    * {o.get('name', '')}{price}{valid}{': ' + o['details'] if o.get('details') else ''}")
    else:
        lines.append("- Prices and offers: NONE are verified. Do not mention any price, discount, offer or free service.")
    if kb["faqs"]:
        lines.append("- Frequently asked questions:")
        lines += [f"    * Q: {f.get('q', '')} A: {f.get('a', '')}" for f in kb["faqs"][:15]]
    if kb["approved_claims"]:
        lines.append("- Claims the owner has approved: " + "; ".join(kb["approved_claims"]))
    if kb["prohibited_claims"]:
        lines.append("- NEVER say or imply any of: " + "; ".join(kb["prohibited_claims"]))
    if kb["brand_voice"]:
        lines.append(f"- Brand voice: {kb['brand_voice']}")
    if kb["instructions"]:
        lines.append(f"- Owner's extra instructions: {kb['instructions']}")
    lines.append("If a fact is not listed above, do not state it. Do not invent services, prices, offers, results, staff names, appointments or guarantees.")
    if kb["safety_profile"] == "health":
        lines.append("HEALTH BUSINESS: never confirm that anyone is a patient or client, never mention anyone's treatment, condition, diagnosis or appointment, "
                     "never promise or imply outcomes, cure or recovery times. Keep health matters private and invite people to contact the business directly.")
    return "\n".join(lines)
