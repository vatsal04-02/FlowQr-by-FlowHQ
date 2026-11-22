"""Milestone 2 Google readiness check: READS and VALIDATION-ONLY patches against ONE designated test profile. It never writes.

    python -m app.cli google-readiness --connection <id> --location locations/<n> --expect-title FlowHQ [--evidence path.json]

Guards (all enforced in code, none can be switched off by a flag):
  * the connection must be ACTIVE and the location's live title must equal --expect-title, or nothing but that one title read is made;
  * every patch goes through `provider.validate_location_patch`, which always sends `validateOnly=true` (the flag is not a parameter);
  * before the validation probes, a harmless NEW-VALUE probe on `labels` (not shown to customers) proves that validateOnly really does not apply
    new values; if the profile changed, every other probe is skipped and the run reports it loudly;
  * the whole profile is read before and after and compared, and the result says whether anything changed.

The evidence it writes contains only what Google answered about the API (HTTP status, error status and reason, field names, counts). It never
stores a token, a phone number, an address, a review or any other customer value.

Exit code: 0 ran to the end with the profile unchanged · 1 a guard stopped it or the profile changed · 2 blocked before any call.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

from app.core.config import settings
from app.services import google as g
from app.services.agent.v2 import fields as v2f
from app.services.google.provider import PERFORMANCE_METRICS, has_business_scope

BIG_MASK = "name,title,phoneNumbers,categories,storefrontAddress,websiteUri,regularHours,specialHours,serviceArea,labels,openInfo,metadata,profile,serviceItems,moreHours,latlng,languageCode,storeCode"
UPDATED_MASK = "title,phoneNumbers,categories,websiteUri,regularHours,specialHours,profile,serviceItems"


def _line(status: str, name: str, detail: str = "") -> None:
    print(f"  {status:<12} {name:<46} {detail}"[:210])


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _shape(obj, depth: int = 0):
    """Field names and sizes only: never values."""
    if isinstance(obj, dict):
        return {k: (_shape(v, depth + 1) if depth < 2 else "…") for k, v in obj.items()}
    if isinstance(obj, list):
        return f"list[{len(obj)}]"
    return type(obj).__name__


class Recorder:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def call(self, name: str, kind: str, fn, describe=lambda r: ""):
        row: dict = {"name": name, "kind": kind}
        try:
            result = fn()
        except g.GoogleApiNotApproved as exc:
            row.update(outcome="api_not_enabled_or_not_approved", http=exc.status, why=exc.why, service=exc.service, message=str(exc)[:200])
            _line("NOT ENABLED", name, f"{exc.why} {exc.service or ''}")
            result = None
        except g.GoogleRateLimited as exc:
            row.update(outcome="rate_limited", http=429, quota_metric=exc.quota_metric)
            _line("RATE LIMITED", name, "HTTP 429")
            result = None
        except g.GoogleAuthRevoked as exc:
            row.update(outcome="auth_failed", message=str(exc)[:200])
            _line("AUTH", name, str(exc)[:120])
            result = None
        except g.GoogleAPIError as exc:
            row.update(outcome="rejected" if 400 <= exc.status < 500 else "error", http=exc.status, google_status=exc.google_status, reason=exc.reason, message=str(exc)[:300])
            _line(f"HTTP {exc.status}", name, f"{exc.google_status or ''} {str(exc)[:110]}")
            result = None
        else:
            detail = describe(result)
            row.update(outcome="ok", http=200, detail=detail)
            _line("OK", name, detail)
        self.rows.append(row)
        return result


def _date(d: date) -> dict:
    return {"year": d.year, "month": d.month, "day": d.day}


def run(args: argparse.Namespace) -> int:
    print("FlowQR Milestone 2: Google readiness (reads and validateOnly patches; nothing is written)")
    if not settings.google_configured:
        print("BLOCKED: GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set. No Google call was made.")
        return 2
    from app.core.db import system_session
    from app.core.security import get_cipher
    from app.models import GoogleConnection, GoogleConnectionStatus

    db = system_session()
    try:
        conn = db.get(GoogleConnection, uuid.UUID(args.connection))
        if conn is None or not conn.refresh_token_encrypted:
            print("BLOCKED: no such connection or it has no stored token. No Google call was made.")
            return 2
        if conn.status != GoogleConnectionStatus.active:
            print(f"BLOCKED: the connection is '{conn.status.value}', not active. This tool only runs on the designated, active test connection.")
            return 2
        refresh = get_cipher().decrypt(conn.refresh_token_encrypted)
    finally:
        db.close()

    provider = g.get_google_provider()
    rec = Recorder()
    ts = rec.call("oauth: refresh access token", "read", lambda: provider.refresh_access_token(refresh),
                  lambda t: f"expires_in={t.expires_in}s business.manage={has_business_scope(t.scope) if t.scope else 'scope not returned'}")
    if ts is None:
        return _finish(args, rec, guard="auth failed", changed=None)
    at, loc = ts.access_token, args.location

    # ---- guard: the live title must be the designated test profile
    title_raw = rec.call("guard: location title", "read", lambda: provider.get_location_raw(at, loc, "name,title"), lambda r: "title read")
    if title_raw is None or (title_raw.get("title") or "").strip().lower() != args.expect_title.strip().lower():
        _line("STOPPED", "guard", f"live title is not the expected designated test profile; no other call was made")
        return _finish(args, rec, guard="title mismatch", changed=None)
    _line("OK", "guard", "title matches the designated test profile")

    accounts = rec.call("accounts.list", "read", lambda: provider.list_accounts(at), lambda a: f"{len(a)} account(s)") or []
    account = accounts[0].name if accounts else None

    # ---- reads
    before = rec.call("locations.get (full read mask)", "read", lambda: provider.get_location_raw(at, loc, BIG_MASK),
                      lambda r: "fields returned: " + ",".join(sorted(k for k in r.keys())))
    if before is None:
        return _finish(args, rec, guard="could not read the profile", changed=None)
    h_before = _digest(before)
    rec.rows[-1]["fields_returned"] = sorted(before.keys())
    rec.rows[-1]["shape"] = _shape(before)

    if account:
        rec.call("reviews.list", "read", lambda: provider.list_reviews(at, account, loc), lambda p: f"{len(p.reviews)} on first page")
        rec.call("localPosts.list", "read", lambda: provider.list_posts(at, account, loc), lambda p: f"{len(p)} post(s)")
        rec.call("media.list", "read", lambda: provider.list_media(at, account, loc), lambda m: f"{len(m)} item(s)")
        rec.call("notificationSetting.get (account)", "read", lambda: provider.get_notification_setting(at, account), lambda r: "fields: " + ",".join(sorted(r)))
    end = date.today() - timedelta(days=3)
    rec.call("performance.fetchMultiDaily (7 days)", "read", lambda: provider.fetch_performance(at, loc, (end - timedelta(days=6)).isoformat(), end.isoformat(), PERFORMANCE_METRICS),
             lambda s: f"{len(s)}/{len(PERFORMANCE_METRICS)} metrics returned data: {sorted(s)}")
    last = end.replace(day=1) - timedelta(days=1)
    first = (last.replace(day=1) - timedelta(days=62)).replace(day=1)
    rec.call("searchkeywords.impressions.monthly", "read", lambda: provider.search_keywords(at, loc, f"{first:%Y-%m}", f"{last:%Y-%m}", limit=100), lambda k: f"{len(k)} term(s)")
    rec.call("locations.getGoogleUpdated", "read", lambda: provider.get_google_updated(at, loc, UPDATED_MASK),
             lambda r: f"diffMask={r['diff_mask']!r} pendingMask={r['pending_mask']!r}")
    rec.call("verifications: getVoiceOfMerchantState", "read", lambda: provider.get_voice_of_merchant_state(at, loc),
             lambda r: "fields: " + ",".join(sorted(r)) + f" | hasVoiceOfMerchant={r.get('hasVoiceOfMerchant')} hasBusinessAuthority={r.get('hasBusinessAuthority')}")
    rec.call("verifications: list", "read", lambda: provider.list_verifications(at, loc), lambda r: "fields: " + ",".join(sorted(r)))
    rec.call("attributes: get (merchant's)", "read", lambda: provider.get_attributes(at, loc), lambda r: "fields: " + ",".join(sorted(r)))
    primary = ((before.get("categories") or {}).get("primaryCategory") or {}).get("name")
    rec.call("attributes: metadata for this location", "read", lambda: provider.list_attribute_metadata(at, parent=loc),
             lambda r: f"{len(r.get('attributeMetadata') or [])} attribute(s)")
    if primary:
        rec.call("attributes: metadata for the primary category", "read", lambda: provider.list_attribute_metadata(at, category_name=primary),
                 lambda r: f"{len(r.get('attributeMetadata') or [])} attribute(s)")
    rec.call("placeActionLinks.list", "read", lambda: provider.list_place_action_links(at, loc), lambda r: "fields: " + ",".join(sorted(r)))

    # ---- semantic proof: a NEW value sent with validateOnly must not be applied
    probe_label = f"flowqr-readiness-probe-{uuid.uuid4().hex[:8]}"
    labels_now = list(before.get("labels") or [])
    label_result = rec.call("validateOnly: NEW label value (semantic proof)", "validate", lambda: provider.validate_location_patch(at, loc, {"labels": labels_now + [probe_label]}, "labels"),
                            lambda r: f"accepted; response fields: {', '.join(sorted(r))}")
    semantics_proven = label_result is not None  # an error answer proves nothing about whether a NEW value would be applied
    proof = provider.get_location_raw(at, loc, BIG_MASK)
    if _digest(proof) != h_before:
        _line("ALERT", "validateOnly semantics", "THE PROFILE CHANGED after a validateOnly request. No further probe was sent.")
        rec.rows.append({"name": "validateOnly semantics", "kind": "guard", "outcome": "profile_changed_after_validate_only"})
        return _finish(args, rec, guard="validateOnly changed the profile", changed=True)
    if semantics_proven:
        _line("OK", "validateOnly semantics", "a new value sent with validateOnly=true was NOT applied (profile identical)")
        rec.rows.append({"name": "validateOnly semantics", "kind": "guard", "outcome": "ok", "detail": "new value not applied"})
    else:
        _line("NOT PROVEN", "validateOnly semantics", "the label probe was rejected, so probes that carry NEW values are skipped; only current-value probes run")
        rec.rows.append({"name": "validateOnly semantics", "kind": "guard", "outcome": "not_proven", "detail": "new-value probes skipped"})

    # ---- probes (each is validateOnly by construction)
    def probe(name: str, body: dict, mask: str):
        # Google allows 10 edits per minute per profile; validation requests appear to count (a 429 was observed on the 11th), so pace them.
        time.sleep(args.pace_seconds)
        rec.call(f"validateOnly: {name}", "validate", lambda: provider.validate_location_patch(at, loc, body, mask),
                 lambda r: f"accepted; response is the location as it WOULD be (fields: {', '.join(sorted(r))})")

    cats = before.get("categories") or {}
    if before.get("profile"):
        probe("description (profile.description)", {"profile": before["profile"]}, "profile")
    if before.get("regularHours"):
        probe("regularHours (current periods)", {"regularHours": before["regularHours"]}, "regularHours")
    if semantics_proven:
      probe("specialHours: one future closed day", {"specialHours": {"specialHourPeriods": [{"startDate": _date(date.today() + timedelta(days=200)), "closed": True}]}}, "specialHours")
    if semantics_proven and before.get("regularHours"):
        probe("specialHours + regularHours together", {"regularHours": before["regularHours"],
              "specialHours": {"specialHourPeriods": [{"startDate": _date(date.today() + timedelta(days=200)), "closed": True}]}}, "regularHours,specialHours")
    if before.get("phoneNumbers"):
        probe("phoneNumbers (current)", {"phoneNumbers": before["phoneNumbers"]}, "phoneNumbers")
    if before.get("websiteUri"):
        probe("websiteUri (current)", {"websiteUri": before["websiteUri"]}, "websiteUri")
    if cats.get("primaryCategory"):
        body = {"categories": {"primaryCategory": {"name": cats["primaryCategory"]["name"]},
                               "additionalCategories": [{"name": c["name"]} for c in cats.get("additionalCategories") or []]}}
        probe("categories (current primary + additional)", body, "categories")
        probe("categories: primaryCategory only (documented sub-field rule)", {"categories": {"primaryCategory": {"name": cats["primaryCategory"]["name"]}}}, "categories.primaryCategory")
    items = before.get("serviceItems") or []
    probe("serviceItems (current items round-trip)", {"serviceItems": items}, "serviceItems")
    if primary and semantics_proven:
        new_item = {"freeFormServiceItem": {"category": primary, "label": {"displayName": "FlowQR validation probe service", "languageCode": "en"}}}
        probe("serviceItems: add ONE new free-form service", {"serviceItems": items + [new_item]}, "serviceItems")
    if before.get("title"):
        probe("title (current; a Level 3 field)", {"title": before["title"]}, "title")
    if before.get("storefrontAddress"):
        probe("storefrontAddress (current; Level 3)", {"storefrontAddress": before["storefrontAddress"]}, "storefrontAddress")
    if before.get("serviceArea"):
        probe("serviceArea (current; Level 3)", {"serviceArea": before["serviceArea"]}, "serviceArea")
    if before.get("openInfo"):
        probe("openInfo (current)", {"openInfo": before["openInfo"]}, "openInfo")
    # the designated test profile may lack these fields entirely: probe a NEW value (validateOnly, semantics already proven above)
    if semantics_proven:
        mon_fri = {"periods": [{"openDay": d, "openTime": {"hours": 9}, "closeDay": d, "closeTime": {"hours": 17}} for d in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY")]}
        future_closed = {"specialHourPeriods": [{"startDate": _date(date.today() + timedelta(days=200)), "closed": True}]}
        if not before.get("regularHours"):
            probe("regularHours: NEW Mon-Fri 09:00-17:00", {"regularHours": mon_fri}, "regularHours")
            probe("regularHours + specialHours: NEW, together", {"regularHours": mon_fri, "specialHours": future_closed}, "regularHours,specialHours")
        if not before.get("phoneNumbers"):
            probe("phoneNumbers: NEW primary phone", {"phoneNumbers": {"primaryPhone": "+91 98765 43210"}}, "phoneNumbers")
        if not before.get("websiteUri"):
            probe("websiteUri: NEW website", {"websiteUri": "https://www.example.com/"}, "websiteUri")
        probe("profile.description: NEW text", {"profile": {"description": "Validation probe description. No change is applied."}}, "profile")
    _v2_probes(provider, at, loc, before, rec, args, semantics_proven)
    # permission boundaries and unsupported fields: these are EXPECTED to be rejected, which is what is being recorded
    probe("EXPECT REJECT: a field that does not exist", {"notARealField": "x"}, "notARealField")
    probe("EXPECT REJECT: output-only field `metadata`", {"metadata": before.get("metadata") or {}}, "metadata")
    probe("EXPECT REJECT/PERMISSION: latlng (approved clients only)", {"latlng": before.get("latlng") or {"latitude": 0, "longitude": 0}}, "latlng")
    probe("EXPECT REJECT: languageCode (immutable)", {"languageCode": before.get("languageCode") or "en"}, "languageCode")

    after = provider.get_location_raw(at, loc, BIG_MASK)
    changed = _digest(after) != h_before
    return _finish(args, rec, guard="passed", changed=changed)


def _v2_probes(provider, at: str, loc: str, before: dict, rec: Recorder, args, semantics_proven: bool) -> None:
    """Local SEO engine V2 (docs/LOCAL_SEO_ENGINE_V2_RUNBOOK.md): does FlowQR's OWN code speak to Google correctly? Each probe sends what the V2 engine would send, built by the SAME functions
    (`build_location_patch`), but only as a validateOnly dry run, or as a read. Nothing is written. The result records, per operation, whether Google accepted it: that is the only thing that can
    move a V2 operation from "mock-tested" to "validated against Google". It says nothing about what a profile ends up showing after a real write.

    Evidence contains counts and outcomes only, never a service name, attribute value, place or any other customer value."""
    if not hasattr(provider, "build_location_patch"):  # a test double that has none of the V2 surface: nothing to probe
        print("  -- Local SEO engine V2 probes skipped: this provider has no V2 operations --")
        return
    print("  -- Local SEO engine V2 probes (dry runs and reads only) --")

    def dry(name: str, changes: dict):
        time.sleep(args.pace_seconds)  # Google: 10 edits per minute per profile; validation requests appear to count
        rec.call(f"V2 validateOnly: {name}", "validate", lambda: provider.validate_changes(at, loc, changes), lambda r: "accepted by Google in a dry run (nothing applied)")

    items = v2f.services_from_google(before.get("serviceItems"))
    rec.rows.append({"name": "V2 normaliser: services round trip", "kind": "local", "outcome": "ok" if v2f.services_from_google(v2f.services_to_google(items)) == items else "mismatch",
                     "detail": f"{len(items)} item(s) read, rebuilt and re-read identically" if v2f.services_from_google(v2f.services_to_google(items)) == items else "the rebuilt list differs from what was read"})
    _line("OK" if rec.rows[-1]["outcome"] == "ok" else "MISMATCH", "V2 normaliser: services round trip", rec.rows[-1]["detail"])
    meta = (before.get("metadata") or {})
    rec.rows.append({"name": "V2 eligibility: metadata.canModifyServiceList", "kind": "local", "outcome": "ok", "detail": f"value={meta.get('canModifyServiceList')!r} (None means Google did not say; FlowQR then assumes NO)"})
    _line("INFO", "V2 eligibility: canModifyServiceList", repr(meta.get("canModifyServiceList")))
    if items and meta.get("canModifyServiceList") is not False:
        dry("services (our builder, the CURRENT complete list)", {"services": items})
    if semantics_proven and meta.get("canModifyServiceList") is not False and (before.get("categories") or {}).get("primaryCategory"):
        dry("services (our builder, current list + ONE new custom item)",
            {"services": v2f.canon_services(items + [{"k": "c", "n": "FlowQR validation probe service", "c": before["categories"]["primaryCategory"]["name"], "l": "en"}])})
    sh = v2f.special_hours_from_google(before.get("specialHours"))
    if sh and before.get("regularHours"):
        dry("special_hours (our builder, the CURRENT list)", {"special_hours": sh})
    if semantics_proven and before.get("regularHours"):
        dry("special_hours (our builder, current list + one future closed day)", {"special_hours": v2f.canon_special_hours(sh + [{"start": (date.today() + timedelta(days=201)).isoformat(), "closed": True}])})
    sa = v2f.service_area_from_google(before.get("serviceArea"))
    if sa and sa["places"]:
        dry("service_area (our builder, the CURRENT area)", {"service_area": sa})
    cats = v2f.categories_from_details({"primary_category": {"id": ((before.get("categories") or {}).get("primaryCategory") or {}).get("name")},
                                        "additional_categories": [{"id": c.get("name")} for c in (before.get("categories") or {}).get("additionalCategories") or []]})
    if cats:
        dry("categories (our builder, primary + additional TOGETHER)", {"categories": cats})
    # ---- reads: attributes and category service types
    attrs = rec.call("V2 read: attributes normalised", "read", lambda: provider.get_attributes_normalized(at, loc), lambda a: f"{len(a)} attribute(s) normalised")
    meta_attrs = rec.call("V2 read: attribute metadata for this location", "read", lambda: provider.attribute_metadata_for_location(at, loc), lambda m: f"{len(m)} attribute(s) offered")
    if attrs is not None and meta_attrs is not None:
        refused = [a["name"] for a in attrs if v2f.validate_attribute_against_metadata(a, meta_attrs.get(a["name"]))]
        rec.rows.append({"name": "V2 check: current attributes pass FlowQR's own metadata check", "kind": "local", "outcome": "ok" if not refused else "mismatch",
                         "detail": f"{len(attrs) - len(refused)} of {len(attrs)} current attribute(s) accepted by FlowQR's check" + (f"; {len(refused)} refused (FlowQR's check may be stricter than Google)" if refused else "")})
        _line("OK" if not refused else "MISMATCH", "V2 check: attributes vs metadata", rec.rows[-1]["detail"])
    primary = ((before.get("categories") or {}).get("primaryCategory") or {}).get("name")
    if primary:
        types = rec.call("V2 read: category service types (view=FULL)", "read", lambda: provider.get_category_service_types(at, [primary]), lambda t: f"{len(t.get(primary, []))} predefined service type(s)")
        if types is not None:
            ids = {x["id"] for x in types.get(primary, [])}
            structured = [x["id"] for x in items if x["k"] == "s"]
            rec.rows.append({"name": "V2 check: structured services are among the category's service types", "kind": "local",
                             "outcome": "ok" if all(i in ids for i in structured) else "mismatch", "detail": f"{len([i for i in structured if i in ids])} of {len(structured)} structured item(s) found in the category's list"})
            _line("OK" if rec.rows[-1]["outcome"] == "ok" else "MISMATCH", "V2 check: service type ids", rec.rows[-1]["detail"])


def _finish(args, rec: Recorder, *, guard: str, changed: bool | None) -> int:
    ok = sum(1 for r in rec.rows if r["outcome"] == "ok")
    print()
    print(f"Calls: {len(rec.rows)}  ok: {ok}  not-ok: {len(rec.rows) - ok}  guard: {guard}")
    print("Profile before/after identical." if changed is False else ("PROFILE CHANGED DURING THE RUN." if changed else "Profile comparison not available."))
    if args.evidence:
        p = Path(args.evidence)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"tool": "google-readiness", "date": date.today().isoformat(), "guard": guard, "profile_changed": changed, "calls": rec.rows}, indent=2, default=str), encoding="utf-8")
        print(f"Evidence written to {p} (API-level facts only; no customer values).")
    return 0 if changed is False else 1


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--connection", required=True, help="google_connections.id of the designated, ACTIVE test connection")
    ap.add_argument("--location", required=True, help="locations/<id> of the designated test profile")
    ap.add_argument("--expect-title", required=True, help="the live title the profile must have (guard against the wrong profile)")
    ap.add_argument("--pace-seconds", type=float, default=7.0, help="pause before each validation request (Google: 10 edits per minute per profile)")
    ap.add_argument("--evidence", help="write the API-level evidence (no customer values) to this JSON file")
