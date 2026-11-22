"""Local SEO engine V2, part 1: the pure logic (no database, no network): canonical forms, Google's stated limits, complete-list safety, evidence rules, and discovery.

These prove FlowQR's own rules. They are NOT evidence about how Google behaves: that is tests/test_seo_v2_contract.py (request shapes from Google's documentation, against a mock) and,
for anything marked live, docs/LOCAL_SEO_ENGINE_V2_TEST_MATRIX.md (which states plainly what has and has not run against a real test profile)."""
from datetime import date

import pytest

from app.services.agent import autonomy_policy as pol
from app.services.agent.v2 import discovery as disc
from app.services.agent.v2 import fields as v2f
from app.services.agent.v2 import keywords as kw
from app.services.agent.v2 import present

KB = {"business": "Gomti Physio", "category": "Physiotherapy clinic", "description": "Physio in Lucknow.", "services": ["Back pain physiotherapy", "Neck pain physiotherapy", "Sports injury rehab"],
      "offers": [], "faqs": [], "approved_claims": [], "prohibited_claims": [], "safety_profile": "general", "hours": ""}
TYPES = [{"id": "job_type_id:back_pain_physiotherapy", "name": "Back pain physiotherapy"}, {"id": "job_type_id:dry_needling", "name": "Dry needling"}]
CUR = [{"k": "s", "id": "job_type_id:dry_needling"}, {"k": "c", "n": "Posture assessment", "c": "categories/gcid:physiotherapist"}]


# ============================================================================ services: the COMPLETE list
def test_a_plan_keeps_every_existing_service_and_adds_only_verified_ones():
    p = disc.plan_services(v2f.canon_services(CUR), KB["services"], TYPES, "categories/gcid:physiotherapist")
    keys = {v2f.service_key(x) for x in p["proposed"]}
    assert {v2f.service_key(x) for x in v2f.canon_services(CUR)} <= keys  # nothing removed
    assert p["removed"] == [] and not v2f.services_removed(v2f.canon_services(CUR), p["proposed"])
    names = {v2f.service_label(x, p["type_names"]) for x in p["added"]}
    assert names == {"Back pain physiotherapy", "Neck pain physiotherapy", "Sports injury rehab"}
    # the one matching Google's predefined list is a structured item, the others are custom items under the primary category
    by = {v2f.service_label(x, p["type_names"]): x for x in p["added"]}
    assert by["Back pain physiotherapy"]["k"] == "s" and by["Back pain physiotherapy"]["id"] == "job_type_id:back_pain_physiotherapy"
    assert by["Neck pain physiotherapy"]["k"] == "c" and by["Neck pain physiotherapy"]["c"] == "categories/gcid:physiotherapist"


def test_a_service_already_on_google_is_never_added_again_even_under_another_form():
    cur = v2f.canon_services([{"k": "s", "id": "job_type_id:back_pain_physiotherapy"}, {"k": "c", "n": "neck  pain physiotherapy!", "c": "categories/gcid:physiotherapist"}])
    p = disc.plan_services(cur, ["Back pain physiotherapy", "Neck Pain Physiotherapy"], TYPES, "categories/gcid:physiotherapist")
    assert p["added"] == []


def test_duplicates_are_removed_and_order_is_stable():
    a = v2f.canon_services([{"k": "c", "n": "A", "c": "x"}, {"k": "c", "n": " a ", "c": "x"}, {"k": "s", "id": "t1"}])
    assert len(a) == 2 and a == v2f.canon_services(list(reversed(a)))


def test_a_complete_list_round_trips_through_google_shape_without_loss():
    cur = v2f.canon_services([{"k": "s", "id": "t1", "d": "Short note"}, {"k": "c", "n": "Custom", "d": "x", "c": "categories/gcid:a", "l": "en", "p": {"currencyCode": "INR", "units": "500"}}])
    g = v2f.services_to_google(cur)
    st = [x for x in g if "structuredServiceItem" in x][0]
    ff = [x for x in g if "freeFormServiceItem" in x][0]
    assert st == {"structuredServiceItem": {"serviceTypeId": "t1", "description": "Short note"}}
    assert ff["freeFormServiceItem"] == {"category": "categories/gcid:a", "label": {"displayName": "Custom", "description": "x", "languageCode": "en"}}
    assert ff["price"] == {"currencyCode": "INR", "units": "500"}  # an existing price is carried through untouched, never invented
    assert v2f.services_from_google(g) == cur


def test_a_free_form_service_without_a_category_cannot_be_sent():
    with pytest.raises(v2f.FieldError):
        v2f.services_to_google([{"k": "c", "n": "No category"}])


def test_service_text_limits_and_links():
    long = v2f.canon_services([{"k": "c", "n": "x" * 141, "c": "c"}])
    assert v2f.services_problems(long)
    assert v2f.services_problems(v2f.canon_services([{"k": "c", "n": "See www.example.com", "c": "c"}]))
    assert v2f.services_problems(v2f.canon_services([{"k": "s", "id": "t", "d": "y" * 301}]))
    assert not v2f.services_problems(v2f.canon_services([{"k": "c", "n": "Fine", "d": "ok", "c": "c"}]))


def test_dropping_an_existing_service_is_a_removal_the_policy_escalates_to_the_owner():
    cur, new = v2f.canon_services(CUR), v2f.canon_services(CUR[:1])
    d = pol.classify("service_update", current=cur, proposed=new, kb=KB)
    assert d.level == 3 and d.effective_type == "significant_removal"
    add = pol.classify("service_update", current=new, proposed=cur, kb=KB)
    assert add.level == 2 and add.effective_type == "service_update"


def test_a_service_not_traced_to_the_business_knowledge_is_refused():
    cur = v2f.canon_services(CUR)
    sneaky = v2f.canon_services(CUR + [{"k": "c", "n": "Cosmetic surgery", "c": "categories/gcid:physiotherapist"}])
    key = v2f.service_key(sneaky[0]) if False else [v2f.service_key(x) for x in sneaky if x.get("n") == "Cosmetic surgery"][0]
    info = {"can_modify_service_list": True}
    for source in ({"kind": "business_knowledge", "refs": ["services"], "service_matches": {}},
                   {"kind": "business_knowledge", "refs": ["services"], "service_matches": {key: "Cosmetic surgery"}}):
        problems = pol.validate_proposal("service_update", field_key="services", current=cur, proposed=sneaky, source=source, proposed_by="agent", kb=KB, tenant_facts={}, info=info)
        assert any("not traced" in p for p in problems), source


def test_a_locked_service_list_is_unavailable_and_an_unknown_one_is_not_assumed_editable():
    cur = v2f.canon_services(CUR)
    new = v2f.canon_services(CUR + [{"k": "c", "n": "Back pain physiotherapy", "c": "c"}])
    src = {"kind": "owner_input", "user_id": "u"}
    for flag, word in ((False, "cannot be edited"), (None, "did not say")):
        p = pol.validate_proposal("service_update", field_key="services", current=cur, proposed=new, source=src, proposed_by="user", kb=KB, tenant_facts={}, info={"can_modify_service_list": flag})
        assert any(word in x for x in p)
    assert disc.service_eligibility({"can_modify_service_list": False})["editable"] is False
    assert disc.service_eligibility({})["editable"] is None
    assert disc.service_eligibility({"can_modify_service_list": True})["editable"] is True


def test_an_unread_service_list_is_unknown_never_empty():
    """The dangerous case: treating 'we have not read it' as 'there are none' would propose a list that replaces everything."""
    assert pol.field_value({"title": "x"}, "services") is None
    assert pol.field_value({"service_items": []}, "services") == []
    p = pol.validate_proposal("service_update", field_key="services", current=None, proposed=v2f.canon_services(CUR), source={"kind": "owner_input", "user_id": "u"}, proposed_by="user", kb=KB,
                              tenant_facts={}, info={"can_modify_service_list": True})
    assert any("no recent read" in x for x in p)


def test_an_empty_service_list_can_never_be_proposed():
    p = pol.validate_proposal("service_update", field_key="services", current=v2f.canon_services(CUR), proposed=[], source={"kind": "owner_input", "user_id": "u"}, proposed_by="user", kb=KB,
                              tenant_facts={}, info={"can_modify_service_list": True})
    assert any("No new services value" in x for x in p)


# ============================================================================ special hours
def sp(start, **kw_):
    return {"start": start, **kw_}


def test_special_hours_follow_googles_period_rules():
    ok = v2f.canon_special_hours([sp("2026-12-25", closed=True), sp("2026-12-31", open="09:00", close="14:00"), sp("2027-01-01", end="2027-01-02", open="22:00", close="02:00")])
    assert not v2f.special_hours_problems(ok, has_regular_hours=True)
    bad = {
        "close before open": v2f.canon_special_hours([sp("2026-12-31", open="14:00", close="09:00")]),
        "24 hours or more": v2f.canon_special_hours([sp("2026-12-31", end="2027-01-01", open="00:00", close="24:00")]),
        "needs both times": v2f.canon_special_hours([sp("2026-12-31", open="09:00")]),
        "next-day close after 11:59": v2f.canon_special_hours([sp("2026-12-31", end="2027-01-01", open="23:00", close="12:30")]),
        "ends two days later": v2f.canon_special_hours([sp("2026-12-31", end="2027-01-02", open="09:00", close="10:00")]),
    }
    for why, v in bad.items():
        assert v2f.special_hours_problems(v, has_regular_hours=True), why


def test_special_hours_need_regular_hours_first_and_reject_two_entries_for_one_date():
    one = v2f.canon_special_hours([sp("2026-12-25", closed=True)])
    assert any("regular opening hours" in p for p in v2f.special_hours_problems(one, has_regular_hours=False))
    assert not any("regular" in p for p in v2f.special_hours_problems(one, has_regular_hours=None))
    dup = v2f.canon_special_hours([sp("2026-12-25", closed=True), sp("2026-12-25", open="10:00", close="12:00")])
    assert any("same date" in p for p in v2f.special_hours_problems(dup, has_regular_hours=True))
    with pytest.raises(v2f.FieldError):
        v2f.canon_special_hours([sp("25-12-2026", closed=True)])
    with pytest.raises(v2f.FieldError):
        v2f.canon_special_hours([sp("2026-02-30", closed=True)])


def test_special_hours_google_shape_round_trip():
    v = v2f.canon_special_hours([sp("2026-12-25", closed=True), sp("2026-12-31", open="09:00", close="14:30")])
    g = v2f.special_hours_to_google(v)
    assert g["specialHourPeriods"][0] == {"startDate": {"year": 2026, "month": 12, "day": 25}, "closed": True}
    assert g["specialHourPeriods"][1]["closeTime"] == {"hours": 14, "minutes": 30}
    assert v2f.special_hours_from_google(g) == v


def test_existing_special_hours_are_kept_and_a_clashing_date_is_a_conflict_not_an_overwrite():
    cur = v2f.canon_special_hours([sp("2026-12-25", closed=True)])
    m = disc.merge_special(cur, v2f.canon_special_hours([sp("2026-12-31", open="09:00", close="14:00")]), date(2026, 11, 22))
    assert [p["start"] for p in m["proposed"]] == ["2026-12-25", "2026-12-31"] and m["conflicts"] == []
    clash = disc.merge_special(cur, v2f.canon_special_hours([sp("2026-12-25", open="10:00", close="12:00")]), date(2026, 11, 22))
    assert clash["conflicts"] == ["2026-12-25"] and clash["proposed"][0]["closed"] is True  # the owner's earlier entry is intact


def test_changing_or_dropping_a_future_special_period_is_a_removal_for_the_owner():
    cur = v2f.canon_special_hours([sp("2099-12-25", closed=True), sp("2099-12-31", open="09:00", close="14:00")])
    assert pol.classify("special_hours_update", current=cur, proposed=cur[:1], kb=KB).level == 3
    changed = v2f.canon_special_hours([sp("2099-12-25", open="10:00", close="12:00"), sp("2099-12-31", open="09:00", close="14:00")])
    assert pol.classify("special_hours_update", current=cur, proposed=changed, kb=KB).level == 3
    added = v2f.canon_special_hours(cur + [sp("2099-12-26", closed=True)])
    assert pol.classify("special_hours_update", current=cur, proposed=added, kb=KB).level == 2


def test_special_hours_are_never_guessed():
    p = pol.validate_proposal("special_hours_update", field_key="special_hours", current=[], proposed=v2f.canon_special_hours([sp("2099-12-25", closed=True)]),
                              source={"kind": "business_knowledge", "refs": ["hours"]}, proposed_by="agent", kb={**KB, "hours": "x"}, tenant_facts={}, info={"has_regular_hours": True})
    assert p  # a business_knowledge source is not accepted for this type at all


def test_holiday_gaps_list_only_fixed_dates_and_say_festivals_are_the_owners_to_enter():
    a = disc.assess_special([], True, date(2026, 12, 10))
    assert [g["date"] for g in a["gaps"]] == ["2026-12-25", "2027-01-01", "2027-01-26"] and "Diwali" in a["note"]  # fixed dates only, inside 60 days
    assert disc.assess_special(v2f.canon_special_hours([sp("2026-12-25", closed=True)]), True, date(2026, 12, 10))["gaps"][0]["date"] == "2027-01-01"
    assert disc.assess_special([], False, date(2026, 12, 10))["needs_regular_hours_first"] is True


# ============================================================================ attributes
META = {"attributes/wi_fi": {"valueType": "ENUM", "displayName": "Wi-Fi", "valueMetadata": [{"value": "free_wifi", "displayName": "Free"}, {"value": "paid_wifi", "displayName": "Paid"}]},
        "attributes/has_wheelchair_accessible_entrance": {"valueType": "BOOL", "displayName": "Wheelchair accessible entrance"},
        "attributes/pay_credit_card": {"valueType": "REPEATED_ENUM", "displayName": "Cards", "repeatable": True, "valueMetadata": [{"value": "visa"}, {"value": "mastercard"}]},
        "attributes/old_thing": {"valueType": "BOOL", "displayName": "Old", "deprecated": True}}


def test_attribute_values_follow_their_type_and_googles_own_metadata():
    ok = [v2f.canon_attribute({"name": "wi_fi", "type": "ENUM", "value": "free_wifi"}), v2f.canon_attribute({"name": "attributes/has_wheelchair_accessible_entrance", "type": "BOOL", "value": True}),
          v2f.canon_attribute({"name": "pay_credit_card", "type": "REPEATED_ENUM", "value": {"set": ["visa"], "unset": ["mastercard"]}})]
    for a in ok:
        assert not v2f.validate_attribute_against_metadata(a, META[a["name"]])
    assert v2f.validate_attribute_against_metadata(v2f.canon_attribute({"name": "wi_fi", "type": "ENUM", "value": "gold"}), META["attributes/wi_fi"])
    assert v2f.validate_attribute_against_metadata(v2f.canon_attribute({"name": "wi_fi", "type": "BOOL", "value": True}), META["attributes/wi_fi"])  # wrong type for this attribute
    assert v2f.validate_attribute_against_metadata(v2f.canon_attribute({"name": "old_thing", "type": "BOOL", "value": True}), META["attributes/old_thing"])  # deprecated: would not be saved
    assert v2f.validate_attribute_against_metadata(v2f.canon_attribute({"name": "made_up", "type": "BOOL", "value": True}), None)  # not offered for this business
    with pytest.raises(v2f.FieldError):
        v2f.canon_attribute({"name": "x", "type": "BOOL", "value": "yes"})  # a string is not a boolean
    with pytest.raises(v2f.FieldError):
        v2f.canon_attribute({"name": "x", "type": "REPEATED_ENUM", "value": {"set": ["a"], "unset": ["a"]}})


def test_attribute_google_shapes_round_trip():
    cur = v2f.attributes_from_google({"attributes": [{"name": "attributes/wi_fi", "valueType": "ENUM", "values": ["free_wifi"]},
                                                      {"name": "attributes/has_wheelchair_accessible_entrance", "valueType": "BOOL", "values": [True]},
                                                      {"name": "attributes/pay_credit_card", "valueType": "REPEATED_ENUM", "repeatedEnumValue": {"setValues": ["visa"], "unsetValues": []}},
                                                      {"name": "attributes/url_menu", "valueType": "URL", "uriValues": [{"uri": "https://example.com/menu"}]}]})
    assert {a["type"] for a in cur} == {"ENUM", "BOOL", "REPEATED_ENUM", "URL"}
    wire = {a["name"]: v2f.attribute_to_google(a) for a in cur}
    assert wire["attributes/wi_fi"] == {"name": "attributes/wi_fi", "values": ["free_wifi"]}
    assert wire["attributes/pay_credit_card"]["repeatedEnumValue"] == {"setValues": ["visa"], "unsetValues": []}
    assert wire["attributes/url_menu"]["uriValues"] == [{"uri": "https://example.com/menu"}]


def test_only_the_attributes_that_differ_are_sent_and_removals_are_named():
    cur = v2f.canon_attributes([{"name": "wi_fi", "type": "ENUM", "value": "free_wifi"}, {"name": "x", "type": "BOOL", "value": True}])
    new = v2f.canon_attributes([{"name": "wi_fi", "type": "ENUM", "value": "paid_wifi"}, {"name": "y", "type": "BOOL", "value": False}])
    send, gone = v2f.attributes_changed(cur, new)
    assert {a["name"] for a in send} == {"attributes/wi_fi", "attributes/y"} and gone == ["attributes/x"]
    assert pol.classify("attribute_change", current=cur, proposed=new, kb=KB).level == 3  # x is dropped: a removal, owner only
    assert pol.classify("attribute_change", current=cur, proposed=v2f.canon_attributes([*cur, {"name": "y", "type": "BOOL", "value": False}]), kb=KB).level == 2


def test_attributes_are_asked_never_assumed():
    a = disc.assess_attributes(META, v2f.canon_attributes([{"name": "wi_fi", "type": "ENUM", "value": "free_wifi"}]))
    assert a["total"] == 3 and a["set"] == 1 and a["deprecated_skipped"] == 1 and a["percent"] == 33
    assert {q["name"] for q in a["unset"]} == {"attributes/has_wheelchair_accessible_entrance", "attributes/pay_credit_card"}
    # an attribute can only come from the owner, never from business knowledge, a competitor or the category
    p = pol.validate_proposal("attribute_change", field_key="attributes", current=[], proposed=v2f.canon_attributes([{"name": "x", "type": "BOOL", "value": True}]),
                              source={"kind": "business_knowledge", "refs": ["services"]}, proposed_by="agent", kb=KB, tenant_facts={})
    assert p and "needs a verified source" in p[0]


# ============================================================================ categories
CANDS = [{"id": "categories/gcid:physical_therapist", "name": "Physical therapist"}, {"id": "categories/gcid:sports_injury_clinic", "name": "Sports injury clinic"},
         {"id": "categories/gcid:pizza_restaurant", "name": "Pizza restaurant"}, {"id": "categories/gcid:physiotherapy_clinic", "name": "Physiotherapy clinic"},
         {"id": "categories/gcid:massage_therapist", "name": "Massage therapist"}]


def test_a_category_is_recommended_only_when_the_owners_own_words_support_it():
    cur = {"primary": "categories/gcid:physiotherapy_clinic", "additional": []}
    a = disc.assess_categories(cur, KB, CANDS, competitor_categories=["Pizza restaurant", "Massage therapist"])
    ids = {r["id"] for r in a["recommendations"]}
    assert "categories/gcid:pizza_restaurant" not in ids  # a competitor having it is not a reason
    assert "categories/gcid:massage_therapist" not in ids  # nothing the owner listed supports it
    assert ids == {"categories/gcid:sports_injury_clinic"}  # supported by the owner's own "Sports injury rehab"; "Physical therapist" is not matched by wording, so it is left to the owner
    assert a["proposed"]["primary"] == "categories/gcid:physiotherapy_clinic"  # the main category is kept
    for r in a["recommendations"]:
        assert r["because"] and r["matched_term"] == "Sports injury rehab"


def test_category_changes_are_a_set_and_owner_only():
    cur = {"primary": "categories/gcid:a", "additional": ["categories/gcid:b"]}
    assert pol.classify("category_set_update", current=cur, proposed={"primary": "categories/gcid:a", "additional": ["categories/gcid:b", "categories/gcid:c"]}, kb=KB).level == 3
    sw = pol.classify("category_set_update", current=cur, proposed={"primary": "categories/gcid:z", "additional": ["categories/gcid:b"]}, kb=KB)
    assert sw.level == 3 and sw.effective_type == "primary_category_change"
    assert pol.SPECS["category_set_update"].level == 3 and pol.validate_permissions({"category_set_update": "auto"})  # can never be pre-authorised


def test_categories_are_capped_and_never_untraced():
    too_many = v2f.canon_categories({"primary": "categories/gcid:p", "additional": [f"categories/gcid:c{i}" for i in range(10)]})
    assert v2f.categories_problems(too_many)
    p = pol.validate_proposal("category_set_update", field_key="categories", current={"primary": "categories/gcid:p", "additional": []},
                              proposed={"primary": "categories/gcid:p", "additional": ["categories/gcid:keyword_bait"]}, source={"kind": "business_knowledge", "refs": ["services", "category"], "category_matches": {}},
                              proposed_by="agent", kb=KB, tenant_facts={})
    assert any("not traced" in x for x in p)


# ============================================================================ regular hours
def test_hours_support_split_periods_after_midnight_and_closed_days_and_catch_mistakes():
    split = [["MONDAY", "09:00", "13:00"], ["MONDAY", "16:00", "20:00"], ["TUESDAY", "22:00", "02:00+1"]]
    assert disc.hours_problems(split) == []  # a day with no entry (Wednesday...) is simply closed
    assert disc.hours_problems([["MONDAY", "09:00", "13:00"], ["MONDAY", "12:00", "15:00"]])  # overlap
    assert disc.hours_problems([["MONDAY", "18:00", "09:00"]])  # closes before it opens (and not marked after-midnight)
    assert disc.hours_problems([["FUNDAY", "09:00", "10:00"]])
    assert disc.hours_problems([["MONDAY", "9", "10"]])


def test_written_hours_are_compared_only_when_every_clause_is_read_exactly():
    p = disc.parse_written_hours("Mon-Sat 9am-6pm; Sun closed")
    assert len([r for r in p if r[0] == "SATURDAY"]) == 1 and ["MONDAY", "09:00", "18:00"] in p and not any(r[0] == "SUNDAY" for r in p)
    assert disc.parse_written_hours("Mon-Fri 9-6") is None  # no am/pm: ambiguous, never guessed
    assert disc.parse_written_hours("open most days") is None
    assert disc.parse_written_hours("") is None
    g = [{"day": d, "open": "09:00", "close": "18:00"} for d in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY")]
    same = disc.assess_hours(g, "Mon-Sat 9am-6pm; Sun closed")
    assert same["comparison"]["same"] is True and same["state"] == "ok"
    diff = disc.assess_hours(g, "Mon-Sat 10am-6pm")
    assert diff["comparison"]["same"] is False and diff["comparison"]["differences"] and diff["comparison"]["proposed"]
    unreadable = disc.assess_hours(g, "we are usually open")
    assert unreadable["comparison"] is None and unreadable["written_readable"] is False  # no comparison, no guess
    assert disc.assess_hours([], None)["state"] == "missing"


def test_the_policy_accepts_after_midnight_and_midnight_close_times():
    ok = [["MONDAY", "22:00", "02:00+1"], ["TUESDAY", "09:00", "24:00"]]
    assert not pol.validate_proposal("hours_update", field_key="hours", current=[["MONDAY", "09:00", "17:00"]], proposed=ok, source={"kind": "owner_input", "user_id": "u"}, proposed_by="user", kb=KB, tenant_facts={})


# ============================================================================ service area and contacts
def test_service_area_rules():
    cur = v2f.canon_service_area({"business_type": "CUSTOMER_LOCATION_ONLY", "region": "IN", "places": [{"name": "Lucknow", "place_id": "p1"}]})
    new = v2f.canon_service_area({"business_type": "CUSTOMER_LOCATION_ONLY", "region": "IN", "places": [{"name": "Lucknow", "place_id": "p1"}, {"name": "Unnao", "place_id": "p2"}]})
    assert not v2f.service_area_problems(new, cur)
    assert v2f.service_area_problems(v2f.canon_service_area({"business_type": "CUSTOMER_AND_BUSINESS_LOCATION", "places": []}), cur)  # switching type changes the address: refused
    many = v2f.canon_service_area({"business_type": "CUSTOMER_LOCATION_ONLY", "region": "IN", "places": [{"name": f"P{i}", "place_id": f"id{i}"} for i in range(21)]})
    assert any("at most 20" in p for p in v2f.service_area_problems(many, cur))
    assert pol.classify("service_area_change", current=cur, proposed=new, kb=KB).level == 3  # always the owner
    assert pol.classify("service_area_change", current=new, proposed=cur, kb=KB).effective_type == "significant_removal"
    g = v2f.service_area_to_google(new)
    assert g == {"businessType": "CUSTOMER_LOCATION_ONLY", "places": {"placeInfos": [{"placeName": "Lucknow", "placeId": "p1"}, {"placeName": "Unnao", "placeId": "p2"}]}, "regionCode": "IN"}
    assert v2f.service_area_from_google(g) == new
    with pytest.raises(v2f.FieldError):
        v2f.canon_service_area({"business_type": "CUSTOMER_LOCATION_ONLY", "places": [{"name": "No id"}]})


def test_a_service_area_only_comes_from_the_owner():
    p = pol.validate_proposal("service_area_change", field_key="service_area", current={"business_type": "CUSTOMER_LOCATION_ONLY", "places": [], "region": "IN"},
                              proposed={"business_type": "CUSTOMER_LOCATION_ONLY", "places": [{"name": "X", "place_id": "p"}], "region": "IN"}, source={"kind": "business_knowledge", "refs": ["services"]},
                              proposed_by="agent", kb=KB, tenant_facts={})
    assert p


def test_contact_assessment_never_prefers_an_unverifiable_value():
    a = disc.assess_contacts({"phone": "+91 98765 43210", "website": "https://a.example.com/"}, "098765-43210", "https://a.example.com")
    assert a["phone"]["state"] == "ok" and a["website"]["state"] == "ok"
    b = disc.assess_contacts({"phone": "+91 98765 43210", "website": "https://a.example.com"}, "+91 90000 00000", "not a url")
    assert b["phone"]["state"] == "differs" and b["website"]["state"] == "record_invalid"
    c = disc.assess_contacts({"phone": None, "website": None}, "+91 90000 00000", "https://b.example.com")
    assert c["phone"]["state"] == "fill" and c["website"]["state"] == "fill"
    assert disc.assess_contacts({"phone": "+91 98765 43210"}, None, None)["phone"]["state"] == "ok_google_only"


def test_the_business_name_is_never_writable():
    assert pol.SPECS["business_name_change"].writable is False and pol.SPECS["business_name_change"].level == 3
    assert "title" not in pol.WRITABLE_FIELDS


# ============================================================================ keywords
def test_keyword_opportunities_come_from_verified_facts_and_carry_their_evidence():
    out = kw.discover(services=KB["services"], category="Physiotherapy clinic", localities=["Lucknow", "Gomti Nagar"], google_terms=[{"keyword": "back pain treatment", "value": 120}, {"keyword": "physio", "below": 10}],
                      tracked=["neck pain physiotherapy in Lucknow"], description="Physio in Lucknow for back pain physiotherapy.", review_topics=["Back pain physiotherapy"])
    terms = [o["term"] for o in out]
    assert terms and all(o["evidence"] for o in out)
    assert "neck pain physiotherapy in Lucknow" not in [t.lower() for t in terms]  # already tracked
    assert not any("pizza" in t.lower() for t in terms)  # nothing the business does not do
    assert any(o["source"] == "google_search_terms" and "120" in o["evidence"][0] for o in out)  # real data, as Google gave it
    below = [o for o in out if o["term"] == "physio"][0]
    assert "fewer than 10" in below["evidence"][0]  # a threshold is shown as a threshold, not as a number
    flat = repr(out).lower()
    assert "volume" not in flat and "difficulty" not in flat and "traffic" not in flat  # no invented search volume, difficulty or traffic
    assert out == sorted(out, key=lambda o: (-o["score"], o["term"]))


def test_keyword_coverage_lowers_priority_and_localities_come_from_the_address():
    a = kw.discover(services=["Back care"], category=None, localities=["Lucknow"], google_terms=None, tracked=[], description="Back care in Lucknow", limit=5)
    b = kw.discover(services=["Back care"], category=None, localities=["Lucknow"], google_terms=None, tracked=[], description="Something else", limit=5)
    assert a[0]["in_description"] is True and b[0]["in_description"] is False and b[0]["score"] > a[0]["score"]
    assert kw.localities_from_address("12 MG Road, Gomti Nagar, Lucknow 226010") == ["Gomti Nagar", "Lucknow"]
    assert kw.localities_from_address(None, ["Unnao, Uttar Pradesh"]) == ["Unnao"]


# ============================================================================ presentation
def test_before_after_for_every_field_shows_what_is_added_and_what_is_removed():
    d = present.describe("services", CUR, CUR + [{"k": "c", "n": "New one", "c": "c"}], {"type_names": {"job_type_id:dry_needling": "Dry needling"}})
    assert d["added"] == ["New one"] and d["removed"] == [] and "Dry needling" in d["before"]
    h = present.describe("special_hours", [], v2f.canon_special_hours([sp("2026-12-25", closed=True)]))
    assert h["added"] == ["2026-12-25: closed"] and h["changed"]
    assert present.describe("description", "old", "new")["changed"] and present.describe("hours", [["MONDAY", "09:00", "18:00"]], [])["removed"] == ["Monday: 09:00-18:00"]
    assert present.describe("services", "garbage", "garbage")["changed"] is False  # an unrecognised value falls back to its text instead of failing
