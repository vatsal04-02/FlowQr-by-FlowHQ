"""Balanced Autonomy, part 1: the policy (pure, deterministic, no database, no Google).

Nothing here talks to Google or a model. These tests pin down WHICH level every kind of change has, that a level can only go up, that evidence is required,
and that nothing a caller or a model sends can choose its own level."""
import inspect

import pytest

from app.services.agent import autonomy_policy as pol
from app.services.agent import executor

KB = {"business": "Gomti Physio", "category": "Physiotherapy clinic", "description": "Physiotherapy for back and neck pain in Lucknow.", "services": ["Back care", "Neck pain physiotherapy"],
      "offers": [], "approved_claims": [], "prohibited_claims": [], "safety_profile": "general", "hours": "", "faqs": [], "brand_voice": "warm", "language": "en", "instructions": "", "audience": ""}
HEALTH = {**KB, "safety_profile": "health"}
TENANT = {"website": "https://gomti.example.com", "phone": "+91 98765 43210", "address": "Gomti Nagar"}
GOOD = ("Gomti Physio is a physiotherapy clinic in Lucknow offering back care and neck pain physiotherapy. Call the clinic to book a visit or to ask a question about our services.")
BIZ_SOURCE = {"kind": "business_knowledge", "refs": ["description", "services"]}


# ============================================================================ 1. every classification (the table the brief defines)

LEVEL1 = ["rank_monitoring", "seo_report", "profile_completeness_analysis", "internal_planning", "ranking_trend_analysis", "description_improve", "text_correction", "service_description_improve"]
LEVEL2 = ["hours_update", "service_update", "contact_update", "secondary_category_update", "publish_content", "upload_photo", "reply_publish", "content_edit", "content_delete",
          "special_hours_update", "attribute_change"]  # V2: services/attributes/special hours are medium risk (a person approves each one)
LEVEL3 = ["business_name_change", "primary_category_change", "address_change", "service_area_change", "primary_contact_change", "significant_removal", "sensitive_claim", "category_set_update"]


@pytest.mark.parametrize("action_type,level", [(t, 1) for t in LEVEL1] + [(t, 2) for t in LEVEL2] + [(t, 3) for t in LEVEL3])
def test_every_action_type_has_its_level(action_type, level):
    fk = "website" if action_type in ("contact_update", "primary_contact_change") else None
    d = pol.classify(action_type, field_key=fk, current=None, proposed="x", kb=KB)
    assert d.level == level and d.risk == {1: "low", 2: "medium", 3: "high"}[level] and d.reasons


def test_the_table_is_exactly_the_policy_nothing_missing_nothing_extra():
    assert set(pol.SPECS) == set(LEVEL1 + LEVEL2 + LEVEL3)
    assert {k for k, s in pol.SPECS.items() if s.internal} == {"rank_monitoring", "seo_report", "profile_completeness_analysis", "internal_planning", "ranking_trend_analysis"}


def test_an_unknown_action_type_is_refused_not_guessed():
    with pytest.raises(pol.PolicyError):
        pol.classify("delete_everything")


# ============================================================================ 2. escalation: a level can only go UP

def test_adding_a_missing_contact_is_level_2_but_replacing_an_existing_one_is_level_3():
    assert pol.classify("contact_update", field_key="website", current="", proposed="https://a.example").level == 2
    d = pol.classify("contact_update", field_key="website", current="https://old.example", proposed="https://new.example")
    assert d.level == 3 and d.effective_type == "primary_contact_change" and "already a website" in " ".join(d.reasons)
    assert pol.classify("contact_update", field_key="phone", current="9876543210", proposed="9123456789").level == 3


def test_removing_information_is_always_level_3_whatever_it_was_called():
    for t, fk, cur, new in (("description_improve", "description", "A real description of the clinic that is long enough.", ""), ("hours_update", "hours", [["MONDAY", "09:00", "18:00"]], []),
                            ("contact_update", "phone", "9876543210", ""), ("text_correction", "description", "Some words here", "")):
        d = pol.classify(t, field_key=fk, current=cur, proposed=new)
        assert d.level == 3 and d.effective_type == "significant_removal", t


def test_a_much_shorter_description_is_a_removal_but_a_comparable_one_stays_level_1():
    cur = "x" * 400
    assert pol.classify("description_improve", current=cur, proposed="y" * 100).level == 3
    assert pol.classify("description_improve", current=cur, proposed="y" * 380).level == 1


def test_dropping_an_open_day_or_a_secondary_category_is_a_removal_but_adding_is_not():
    mon, tue = ["MONDAY", "09:00", "18:00"], ["TUESDAY", "09:00", "18:00"]
    assert pol.classify("hours_update", current=[mon, tue], proposed=[mon]).level == 3
    assert pol.classify("hours_update", current=[mon], proposed=[mon, tue]).level == 2
    assert pol.classify("secondary_category_update", current=["c1", "c2"], proposed=["c1"]).level == 3
    assert pol.classify("secondary_category_update", current=["c1"], proposed=["c1", "c2"]).level == 2


def test_health_claims_in_a_health_business_description_need_the_owner():
    d = pol.classify("description_improve", current="old", proposed="We treat back pain and cure sciatica with clinically proven methods.", kb=HEALTH)
    assert d.level == 3 and d.effective_type == "sensitive_claim"
    assert pol.classify("description_improve", current="old", proposed="A physiotherapy clinic in Lucknow with friendly staff and flexible hours.", kb=HEALTH).level == 1
    assert pol.classify("description_improve", current="old", proposed="We treat many people every week.", kb={**KB, "category": "Cafe", "safety_profile": "general"}).level == 1  # a non-health business is not held to the health rule


def test_classification_never_lowers_a_level_whatever_the_values():
    import itertools
    values = [None, "", "a", "https://x.example", [], [["MONDAY", "09:00", "18:00"]], "z" * 500]
    for t, spec in pol.SPECS.items():
        if spec.internal:
            continue
        fk = spec.field or "website"
        for cur, new in itertools.product(values, values):
            try:
                d = pol.classify(t, field_key=fk, current=cur, proposed=new, kb=HEALTH)
            except pol.PolicyError:
                continue
            assert d.level >= spec.level, (t, cur, new)


# ============================================================================ 3. the model (or any caller) cannot choose a level

def test_no_function_that_creates_an_action_accepts_a_level_or_authorisation():
    params = set(inspect.signature(executor.propose).parameters)
    assert not params & {"level", "policy_level", "authorization", "status", "risk", "risk_level", "effective_type", "autonomous", "approved"}
    assert not set(inspect.signature(pol.classify).parameters) & {"level", "policy_level", "authorization"}


# ============================================================================ 4. who authorises what

def decision(t, **kw):
    return pol.classify(t, **kw)


@pytest.mark.parametrize("t,enabled,suspended,perms,expected", [
    ("description_improve", False, False, {}, "owner"),  # autonomy is off by default: even Level 1 asks
    ("description_improve", True, False, {}, "policy"),
    ("description_improve", True, True, {}, "owner"),  # suspended
    ("description_improve", True, False, {"description_improve": "ask"}, "owner"),
    ("hours_update", True, False, {}, "owner"),  # Level 2 defaults to asking
    ("hours_update", True, False, {"hours_update": "ask"}, "owner"),
    ("hours_update", True, False, {"hours_update": "auto"}, "preauthorized"),  # an owner's pre-authorisation for THAT type
    ("hours_update", False, False, {"hours_update": "auto"}, "owner"),  # ...which does nothing while autonomy is off
    ("hours_update", True, True, {"hours_update": "auto"}, "owner"),
    ("service_update", True, False, {"hours_update": "auto"}, "owner"),  # a pre-authorisation for one type authorises no other
    ("primary_category_change", True, False, {"primary_category_change": "auto"}, "owner"),  # Level 3 can never be automatic, even if the data says "auto"
    ("business_name_change", True, False, {}, "owner"),
])
def test_authorisation_resolution(t, enabled, suspended, perms, expected):
    assert pol.authorization_for(decision(t), autonomy_enabled=enabled, suspended=suspended, permissions=perms) == expected


def test_a_preauthorisation_for_a_type_does_not_cover_an_escalated_change_of_that_type():
    d = pol.classify("contact_update", field_key="website", current="https://old.example", proposed="https://new.example")  # became Level 3
    assert pol.authorization_for(d, autonomy_enabled=True, suspended=False, permissions={"contact_update": "auto", "primary_contact_change": "ask"}) == "owner"


def test_permission_validation_refuses_level_3_auto_unknown_types_and_bad_values():
    assert pol.validate_permissions({"hours_update": "auto", "description_improve": "off"}) == []
    assert any("never be pre-authorised" in p for p in pol.validate_permissions({"primary_category_change": "auto"}))
    assert any("not an action type" in p for p in pol.validate_permissions({"drop_database": "auto"}))
    assert any("not an action type" in p for p in pol.validate_permissions({"rank_monitoring": "off"}))  # internal analysis is not a switch
    assert any("choose one of" in p for p in pol.validate_permissions({"hours_update": "yes"}))
    assert pol.validate_permissions({"primary_category_change": "ask", "address_change": "off"}) == []


# ============================================================================ 5. evidence and facts: missing, conflicting, unverified

def val(t, **kw):
    base = dict(field_key=None, current="", proposed=GOOD, source=BIZ_SOURCE, proposed_by="agent", kb=KB, tenant_facts=TENANT)
    base.update(kw)
    return pol.validate_proposal(t, **base)


def test_a_description_from_verified_facts_passes():
    assert val("description_improve") == []


def test_missing_evidence_blocks_it():
    assert any("neither a description nor services" in p for p in val("description_improve", kb={**KB, "description": "", "services": []}))
    assert any("'services' is empty" in p for p in val("description_improve", kb={**KB, "services": []}))
    assert any("names no business-knowledge fields" in p for p in val("description_improve", source={"kind": "business_knowledge", "refs": []}))
    assert any("No new description" in p for p in val("description_improve", proposed=""))


def test_an_unverified_or_wrong_kind_of_source_is_refused():
    assert any("verified source of kind" in p for p in val("description_improve", source={"kind": "ai_guess"}))
    assert any("verified source of kind" in p for p in val("hours_update", source={"kind": "business_knowledge", "refs": ["hours"]}, proposed=[["MONDAY", "09:00", "18:00"]]))
    assert any("verified source" in p for p in val("contact_update", field_key="website", proposed="https://x.example", source={"kind": "google_profile"}))


def test_the_agent_cannot_claim_a_value_came_from_the_owner():
    p = val("hours_update", source={"kind": "owner_input", "user_id": "u"}, proposed=[["MONDAY", "09:00", "18:00"]], proposed_by="agent")
    assert any("cannot be attributed to the owner" in x for x in p)
    assert val("hours_update", source={"kind": "owner_input", "user_id": "u"}, proposed=[["MONDAY", "09:00", "18:00"]], proposed_by="user") == []


def test_conflicting_facts_between_the_proposal_and_the_business_record_block_it():
    src = {"kind": "tenant_record", "refs": ["website"]}
    assert val("contact_update", field_key="website", proposed=pol.canon("website", "https://gomti.example.com"), source=src) == []
    assert any("does not match the website in the business record" in p for p in val("contact_update", field_key="website", proposed=pol.canon("website", "https://other.example"), source=src))
    assert any("no website" in p for p in val("contact_update", field_key="website", proposed="x", source=src, tenant_facts={"website": None}))


def test_invented_prices_offers_claims_links_and_phone_numbers_in_a_description_are_blocked():
    for text, fragment in ((GOOD + " Sessions cost ₹500.", "price"), (GOOD + " Get 20% off this week.", "offer"), (GOOD + " Visit https://gomti.example.com now.", "link"),
                           (GOOD + " Call 9876543210 today.", "phone number")):
        assert any(fragment in p.lower() for p in val("description_improve", proposed=text)), fragment
    assert any("prohibited" in p.lower() or "not allowed" in p.lower() for p in val("description_improve", kb={**KB, "prohibited_claims": ["family dining"]}, proposed=GOOD + " Ideal for family dining."))
    assert any("characters" in p for p in val("description_improve", proposed="Too short."))
    assert any("same as the one on Google" in p for p in val("description_improve", current=GOOD))


def test_a_safe_correction_changes_spelling_not_words():
    cur = "We offer physioterapy for back pain and neck pain."
    assert pol.correction_is_safe(cur, "We offer physiotherapy for back pain and neck pain.")
    assert pol.correction_is_safe("call us today", "Call us today.")
    assert not pol.correction_is_safe(cur, cur + " Free consultation for everyone.")  # adds words
    assert not pol.correction_is_safe("We open at 9 am", "We open at 8 am")  # changes a number
    assert not pol.correction_is_safe("Visit us", "Visit us at https://x.example")
    assert not pol.correction_is_safe("best clinic in town", "cheapest clinic in town")  # a different word, not a typo
    assert val("text_correction", current=cur, proposed="We offer physiotherapy for back pain and neck pain.", source={"kind": "google_profile"}) == []
    assert any("not a safe correction" in p for p in val("text_correction", current=cur, proposed=cur + " More.", source={"kind": "google_profile"}))


def test_hours_must_be_well_formed_and_a_noop_is_refused():
    assert any("non-empty list" in p for p in val("hours_update", proposed=[], source={"kind": "owner_input"}, proposed_by="user"))
    assert any("HH:MM" in p for p in val("hours_update", proposed=[["MONDAY", "9am", "6pm"]], source={"kind": "owner_input"}, proposed_by="user"))
    same = [["MONDAY", "09:00", "18:00"]]
    assert any("nothing to change" in p for p in val("hours_update", current=same, proposed=same, source={"kind": "owner_input"}, proposed_by="user"))


# ============================================================================ 6. fingerprints are stable and order-insensitive where they should be

def test_canonical_values_compare_what_matters():
    assert pol.canon("description", "  a  b\n c ") == "a b c"
    assert pol.canon("website", "https://X.example/") == "https://x.example"
    assert pol.canon("phone", "+91 98765-43210") == pol.canon("phone", "9876543210")
    assert pol.canon("hours", [{"day": "TUESDAY", "open": "09:00", "close": "17:00"}, {"day": "MONDAY", "open": "09:00", "close": "17:00"}]) == \
        pol.canon("hours", [{"day": "MONDAY", "open": "09:00", "close": "17:00"}, {"day": "TUESDAY", "open": "09:00", "close": "17:00"}])
    assert pol.canon("additional_categories", [{"id": "b"}, {"id": "a"}]) == ["a", "b"]
    assert pol.fingerprint({"a": 1, "b": 2}) == pol.fingerprint({"b": 2, "a": 1}) and pol.fingerprint("x") != pol.fingerprint("y")
    assert pol.field_value({"description": " hi  there "}, "description") == "hi there"
