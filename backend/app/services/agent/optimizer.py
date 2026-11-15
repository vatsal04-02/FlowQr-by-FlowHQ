"""AI Profile Optimizer: a plain-language check of one Google Business Profile, from what Google last returned (the daily snapshot).

Deterministic rules, each with the reason and the next step. The AI only writes text (the description), from the knowledge base and
the search terms Google reported; every change waits for the owner's approval. Rules we follow on purpose:
* never suggest adding keywords to the business name (Google's guidelines forbid it) and never promise rankings;
* a check is "unknown" when Google didn't return that part, never guessed as missing or complete.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from app.models import GbpSnapshot
from app.services.agent.snapshots import DESCRIPTION_MIN

DESCRIPTION_MAX = 750  # Google's limit for profile.description


def search_terms_line(snap: GbpSnapshot | None) -> str | None:
    """'Search terms people used to find this profile (from Google): a, b, c' or None when Google hasn't reported any."""
    kws = ((snap.performance or {}).get("keywords") if snap else None) or []
    terms = [k["keyword"] for k in kws if k.get("keyword") and k.get("value")][:12]
    return "Search terms people used to find this profile (reported by Google): " + ", ".join(terms) if terms else None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9ऀ-ॿ ]+", " ", (s or "").lower()).strip()


def checks(snap: GbpSnapshot | None, kb: dict, rank: dict | None = None) -> list[dict]:
    """[{key, title, state: ok|improve|missing|unknown, detail, action, href}] in the order an owner should act on them."""
    info = (snap.info if snap else None) or None
    out: list[dict] = []

    def add(key, title, state, detail, action=None, href=None):
        out.append({"key": key, "title": title, "state": state, "detail": detail, "action": action, "href": href})

    if info is None:
        add("profile", "Profile details", "unknown", "Google hasn't returned this profile yet. Refresh from Google to check it.", "Check Google now", None)
        return out

    status = info.get("open_status")
    if status in ("CLOSED_TEMPORARILY", "CLOSED_PERMANENTLY"):
        add("open", "Open status", "missing", f"Google shows this business as {status.replace('_', ' ').lower()}. Customers may not visit.", "Fix it in Google Business Profile", None)

    desc = (info.get("description") or "").strip()
    title = (info.get("title") or "").strip()
    if not desc:
        add("description", "Description", "missing", "No description. Customers read it to decide if you're the right place.", "Write one with AI", "#description")
    elif len(desc) < DESCRIPTION_MIN:
        add("description", "Description", "improve", f"Only {len(desc)} characters. Google allows {DESCRIPTION_MAX}; 400+ lets you explain your services.", "Improve it with AI", "#description")
    else:
        problems = []
        if re.search(r"https?://|www\.", desc, re.I):
            problems.append("contains a link (Google may reject it)")
        if re.search(r"(\+?\d[\d \-]{8,}\d)", desc):
            problems.append("contains a phone number (Google may reject it)")
        if title and _norm(desc).count(_norm(title)) > 1:
            problems.append("repeats the business name, which reads like keyword stuffing")
        if sum(1 for c in desc if c.isupper()) > max(20, len(desc) * 0.3):
            problems.append("uses a lot of capital letters")
        terms = [k["keyword"] for k in ((snap.performance or {}).get("keywords") or []) if k.get("keyword") and k.get("value")][:10]
        unused = [t for t in terms if _norm(t) not in _norm(desc) and _norm(title) not in _norm(t)]
        if problems:
            add("description", "Description", "improve", "Your description " + "; ".join(problems) + ".", "Improve it with AI", "#description")
        elif len(unused) >= 3:
            add("description", "Description", "improve", f"People find you by searching for things like \"{unused[0]}\" and \"{unused[1]}\", which your description doesn't mention. "
                "Mention what genuinely applies, naturally.", "Improve it with AI", "#description")
        else:
            add("description", "Description", "ok", f"{len(desc)} characters, clear of links and phone numbers.")

    if not info.get("primary_category"):
        add("category", "Main category", "missing", "No main category. It decides which searches you can appear in.", "Choose a category", "/gbp/info")
    elif not info.get("additional_categories"):
        add("category", "Categories", "improve", f"Only \"{info['primary_category']['name']}\". Add other categories that truly describe what you do (up to 9).", "Add categories", "/gbp/info")
    else:
        add("category", "Categories", "ok", f"{info['primary_category']['name']} + {len(info['additional_categories'])} more.")

    services = info.get("services")
    kb_services = [s if isinstance(s, str) else (s.get("name") or "") for s in (kb.get("services") or [])]
    if services is None:
        add("services", "Services", "unknown", "Google didn't return a services list for this profile.")
    elif not services:
        hint = f" Your business brain lists {len(kb_services)}: {', '.join(kb_services[:4])}{'…' if len(kb_services) > 4 else ''}." if kb_services else ""
        add("services", "Services", "missing", "No services are listed on Google." + hint + " Add them in Google Business Profile (services can't be edited through FlowQR yet).", None, None)
    else:
        on_google = {_norm(s) for s in services}
        missing = [s for s in kb_services if s and _norm(s) not in on_google]
        if missing:
            add("services", "Services", "improve", f"{len(services)} on Google. Not listed there yet: {', '.join(missing[:4])}{'…' if len(missing) > 4 else ''}.", None, None)
        else:
            add("services", "Services", "ok", f"{len(services)} services listed.")

    if not info.get("hours"):
        add("hours", "Opening hours", "missing", "No opening hours. Google may show you as \"hours unknown\".", "Add hours", "/gbp/hours")
    else:
        days = {h["day"] for h in info["hours"]}
        add("hours", "Opening hours", "ok", f"Set for {len(days)} {'day' if len(days) == 1 else 'days'} a week.")
        upcoming = [s for s in (info.get("special_hours") or []) if s.get("date") and s["date"] >= date.today().isoformat()]
        if not upcoming:
            add("special_hours", "Holiday hours", "improve", "No special hours for upcoming holidays. Add them before festivals so customers aren't turned away.", "Open Google Business Profile", None)

    for key, label, why in (("phone", "Phone number", "so customers can call"), ("website", "Website", "so customers can learn more")):
        if (info.get(key) or "").strip():
            add(key, label, "ok", "Set.")
        else:
            add(key, label, "missing", f"Missing. Add one {why}.", "Edit business info", "/gbp/info")

    if title and (len(title) > 60 or re.search(r"[|,;/]| - |best|top|no\.? ?1|near me|cheap", title, re.I)):
        add("name", "Business name", "improve", "Google's guidelines say the name should be exactly your real-world name, without extra words, locations or "
            "keywords. A name with extras can be suspended. FlowQR never suggests adding keywords to it.", None, None)

    media = (snap.media if snap else None)
    if media is not None:
        cats = {m.get("category") for m in media}
        need = [c for c in ("COVER", "EXTERIOR", "INTERIOR", "TEAMS") if c not in cats]
        if need:
            names = {"COVER": "cover", "EXTERIOR": "outside", "INTERIOR": "inside", "TEAMS": "team"}
            add("photos", "Photos", "improve" if media else "missing", f"{len(media)} {'photo' if len(media) == 1 else 'photos'} on Google. Missing types: {', '.join(names[c] for c in need)}.", "Add photos", "/gbp/photos")
        else:
            add("photos", "Photos", "ok", f"{len(media)} photos, including cover, exterior, interior and team.")

    posts = (snap.posts if snap else None)
    if posts is not None:
        newest = max((p.get("created_at") or "" for p in posts), default="")
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(newest.replace("Z", "+00:00"))).days if newest else None
        if age is None or age > 14:
            add("posts", "Google posts", "improve", "No posts yet." if age is None else f"Last post {age} days ago. A post every week or two keeps the profile fresh.", "Plan a post", "/gbp/posts")
        else:
            add("posts", "Google posts", "ok", f"Last post {age} days ago.")

    if rank and rank.get("measured"):  # measured search visibility (services/agent/learning.rank_summary); absent when nothing has been measured
        weak, nf = rank.get("weak") or [], rank.get("not_found") or []
        if weak:
            names = ", ".join(f"\"{w['keyword']}\"" for w in weak[:3])
            add("visibility", "Search visibility", "improve", f"{len(weak)} of {rank['measured']} tracked search terms did not show your business in the first 10 Google Places results ({len(nf)} not in the first 20), e.g. {names}. "
                "This is a measurement around one point, not a guaranteed Google Maps ranking.", "See the ranking for these terms", "/gbp/rank")
        else:
            add("visibility", "Search visibility", "ok", f"All {rank['measured']} tracked search terms show your business in the first 10 Google Places results (measured, not guaranteed).")

    if snap and snap.fetched_at and snap.fetched_at < datetime.now(timezone.utc) - timedelta(days=7):
        add("freshness", "Last checked", "improve", "FlowQR last read this profile over a week ago. Refresh to check again.", "Check Google now", None)

    order = {"missing": 0, "improve": 1, "unknown": 2, "ok": 3}
    return sorted(out, key=lambda c: order[c["state"]])


def score(items: list[dict]) -> int | None:
    rated = [c for c in items if c["state"] != "unknown"]
    if not rated:
        return None
    return round(100 * sum(1 if c["state"] == "ok" else 0.5 if c["state"] == "improve" else 0 for c in rated) / len(rated))


# Why each kind of check matters, in the owner's words. None of these claim a ranking effect: they say what the field is for.
WHY = {
    "description": "The description is the one place to say in your own words who you serve and what you do. People read it to decide whether you are the right place, and it is where Google looks for what your business is about.",
    "category": "Categories tell Google which kinds of searches your profile is relevant for, so the main one must be your real core service and extras must be things you truly do.",
    "services": "A services list lets customers see exactly what you offer before they call, and keeps your profile consistent with what you tell the AI.",
    "hours": "Customers decide when to come from your hours. Missing hours show as 'hours unknown', which costs visits.",
    "special_hours": "Festivals and holidays change when you are open. Showing it avoids turned-away customers and bad reviews.",
    "phone": "A phone number turns a search into a call, which is one of the main actions people take from a profile.",
    "website": "A website link gives interested customers somewhere to learn more or book.",
    "photos": "People look at photos before they visit. Google shows them by type (cover, outside, inside, team), so each type should have real photos.",
    "posts": "A recent post shows the business is active and gives something current to read.",
    "name": "Google's guidelines require your real-world name. A name with extra keywords or places can get the profile suspended.",
    "open": "A profile marked closed is skipped by customers.",
    "freshness": "The check is only as current as the last time FlowQR read your profile.",
    "profile": "Without the profile from Google nothing can be assessed.",
    "visibility": "Where your business appears for the searches you track. It is a measurement, and several things move it that no profile edit controls (competitors, season, the searcher's place).",
}


def explain(items: list[dict], snap: GbpSnapshot | None, kb: dict, pending_description: str | None = None) -> list[dict]:
    """Add the six parts an owner needs to act on a check, all from data we hold: current state, problem, recommendation, reason, evidence, and a preview of the change where one exists.
    Nothing here is generated by a model, so it is identical every time and can be tested."""
    info = (snap.info if snap else None) or {}
    perf = (snap.performance if snap else None) or {}
    terms = [k["keyword"] for k in (perf.get("keywords") or []) if k.get("keyword") and k.get("value")][:10]
    title = (info.get("title") or "").strip()
    desc = (info.get("description") or "").strip()
    kb_services = [s_ if isinstance(s_, str) else (s_.get("name") or "") for s_ in (kb.get("services") or [])]
    out = []
    for c in items:
        k, e = c["key"], {}
        current = c["detail"]
        if k == "description":
            current = desc or "(no description yet)"
            unused = [t for t in terms if _norm(t) not in _norm(desc) and _norm(title) not in _norm(t)]
            e = {"characters": len(desc), "search_terms_not_mentioned": unused[:5], "services_in_business_brain": kb_services[:6]}
        elif k == "category":
            pc, extra = (info.get("primary_category") or {}).get("name"), [x.get("name") for x in (info.get("additional_categories") or []) if x.get("name")]
            current = f"Main: {pc or 'none'}; others: {', '.join(extra) or 'none'}"
            e = {"search_terms_google_reported": terms[:5], "services_in_business_brain": kb_services[:6]}
        elif k == "services":
            on_google = [x if isinstance(x, str) else x.get("name") for x in (info.get("services") or [])]
            current = ", ".join(on_google[:8]) or "none listed"
            e = {"on_google": len(on_google), "in_business_brain_not_on_google": [x for x in kb_services if _norm(x) not in {_norm(y) for y in on_google if y}][:6]}
        elif k in ("hours", "special_hours"):
            e = {"days_set": len({h["day"] for h in (info.get("hours") or [])}), "upcoming_special_hours": len([x for x in (info.get("special_hours") or []) if x.get("date", "") >= date.today().isoformat()])}
        elif k == "photos":
            cats: dict[str, int] = {}
            for m in (snap.media if snap and snap.media else []):
                cats[m.get("category") or "OTHER"] = cats.get(m.get("category") or "OTHER", 0) + 1
            e = {"photos": sum(cats.values()), "by_category": cats}
        elif k == "posts":
            e = {"posts_seen": len(snap.posts) if snap and snap.posts is not None else None}
        c2 = {**c, "current": current, "problem": c["detail"] if c["state"] != "ok" else None, "recommendation": c.get("action") or ("Nothing to do." if c["state"] == "ok" else None),
              "reason": WHY.get(k, ""), "evidence": {**e, "read_from_google_at": snap.fetched_at.isoformat() if snap and snap.fetched_at else None},
              "preview": ({"kind": "description", "text": pending_description} if k == "description" and pending_description else None)}
        out.append(c2)
    return out
