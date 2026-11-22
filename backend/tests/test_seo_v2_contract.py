"""Local SEO engine V2, part 2: the REAL provider code against a mock HTTP transport, for every new Google operation.

Request shapes come from Google's Business Information reference (read 2026-11-22; docs/LOCAL_SEO_ENGINE_V2_AUDIT.md lists each page). They prove FlowQR sends what the documentation says and
reads what the documentation says it will get. They do NOT prove Google behaves as documented: that needs a live, approved project and a dedicated test profile (see the test matrix)."""
import pytest

from app.services import google as g
from app.services.agent.v2 import fields as v2f
from tests.test_google_contract import INFO, LOC, body, provider, q

SERVICES = v2f.canon_services([{"k": "s", "id": "job_type_id:dry_needling"}, {"k": "c", "n": "Posture assessment", "c": "categories/gcid:physiotherapist"}])
LOCATION_V2 = {"name": LOC, "title": "Gomti Physio", "languageCode": "en", "profile": {"description": "d"},
               "categories": {"primaryCategory": {"name": "categories/gcid:physiotherapist", "displayName": "Physiotherapist"}, "additionalCategories": []},
               "regularHours": {"periods": [{"openDay": "MONDAY", "openTime": {"hours": 9}, "closeDay": "MONDAY", "closeTime": {"hours": 18}}]},
               "metadata": {"canModifyServiceList": True, "hasPendingEdits": False, "hasGoogleUpdated": True},
               "serviceItems": [{"structuredServiceItem": {"serviceTypeId": "job_type_id:dry_needling"}},
                                {"freeFormServiceItem": {"category": "categories/gcid:physiotherapist", "label": {"displayName": "Posture assessment"}}, "price": {"currencyCode": "INR", "units": "500"}}],
               "specialHours": {"specialHourPeriods": [{"startDate": {"year": 2026, "month": 12, "day": 25}, "closed": True}]},
               "serviceArea": {"businessType": "CUSTOMER_LOCATION_ONLY", "regionCode": "IN", "places": {"placeInfos": [{"placeName": "Lucknow", "placeId": "p1"}]}}}


def test_details_read_the_service_list_special_hours_service_area_and_eligibility_flags():
    p, wire = provider((200, LOCATION_V2))
    d = p.get_location_details("AT", LOC)
    mask = q(wire.last())["readMask"][0].split(",")
    assert {"serviceItems", "specialHours", "serviceArea", "metadata", "regularHours"} <= set(mask)
    assert d["can_modify_service_list"] is True and d["has_regular_hours"] is True and d["has_google_updated"] is True
    assert {x["k"] for x in d["service_items"]} == {"s", "c"} and [x for x in d["service_items"] if x["k"] == "c"][0]["p"] == {"currencyCode": "INR", "units": "500"}
    assert d["special_hours_periods"] == [{"start": "2026-12-25", "end": "2026-12-25", "closed": True, "open": None, "close": None}]
    assert d["service_area"]["places"] == [{"name": "Lucknow", "place_id": "p1"}] and d["service_area"]["business_type"] == "CUSTOMER_LOCATION_ONLY"
    assert d["services"] == ["Posture assessment", "job_type_id:dry_needling"] or set(d["services"]) == {"Posture assessment", "job_type_id:dry_needling"}  # the legacy name list is unchanged


def test_a_missing_service_flag_is_unknown_not_true():
    p, _ = provider((200, {**LOCATION_V2, "metadata": {}}))
    assert p.get_location_details("AT", LOC)["can_modify_service_list"] is None


def test_a_service_update_sends_the_complete_list_under_serviceItems_only():
    p, wire = provider((200, LOCATION_V2), (200, LOCATION_V2))
    p.update_location("AT", LOC, {"services": SERVICES})
    patch = wire.requests[0]
    assert patch.method == "PATCH" and q(patch) == {"updateMask": ["serviceItems"]} and "validateOnly" not in q(patch)
    items = body(patch)["serviceItems"]
    assert len(items) == 2 and set(body(patch)) == {"serviceItems"}  # nothing else in the body: no other field can be touched
    assert {"structuredServiceItem": {"serviceTypeId": "job_type_id:dry_needling"}} in items


def test_validate_changes_is_a_dry_run_that_cannot_be_sent_without_validate_only():
    p, wire = provider((200, {}))
    assert p.validate_changes("AT", LOC, {"services": SERVICES}) == {}
    r = wire.last()
    assert r.method == "PATCH" and q(r) == {"updateMask": ["serviceItems"], "validateOnly": ["true"]}
    assert len(body(r)["serviceItems"]) == 2  # the SAME body update_location would send
    assert len(wire.requests) == 1


def test_a_google_validation_error_is_raised_not_swallowed():
    p, _ = provider((400, {"error": {"code": 400, "message": "serviceItems[1] invalid", "status": "INVALID_ARGUMENT"}}))
    with pytest.raises(g.GoogleAPIError) as e:
        p.validate_changes("AT", LOC, {"services": SERVICES})
    assert e.value.status == 400 and "invalid" in str(e.value)


def test_special_hours_are_sent_whole_under_one_mask():
    p, wire = provider((200, LOCATION_V2), (200, LOCATION_V2))
    periods = v2f.canon_special_hours([{"start": "2026-12-25", "closed": True}, {"start": "2026-12-31", "open": "09:00", "close": "14:00"}])
    p.update_location("AT", LOC, {"special_hours": periods})
    patch = wire.requests[0]
    assert q(patch) == {"updateMask": ["specialHours"]} and set(body(patch)) == {"specialHours"}
    assert len(body(patch)["specialHours"]["specialHourPeriods"]) == 2


def test_a_service_area_patch_sends_business_type_places_and_region():
    p, wire = provider((200, LOCATION_V2), (200, LOCATION_V2))
    area = v2f.canon_service_area({"business_type": "CUSTOMER_LOCATION_ONLY", "region": "IN", "places": [{"name": "Lucknow", "place_id": "p1"}, {"name": "Unnao", "place_id": "p2"}]})
    p.update_location("AT", LOC, {"service_area": area})
    patch = wire.requests[0]
    assert q(patch) == {"updateMask": ["serviceArea"]}
    assert body(patch)["serviceArea"] == {"businessType": "CUSTOMER_LOCATION_ONLY", "regionCode": "IN", "places": {"placeInfos": [{"placeName": "Lucknow", "placeId": "p1"}, {"placeName": "Unnao", "placeId": "p2"}]}}


def test_a_category_set_sends_primary_and_additional_together_in_one_categories_object():
    p, wire = provider((200, LOCATION_V2), (200, LOCATION_V2))
    p.update_location("AT", LOC, {"categories": {"primary": "categories/gcid:physiotherapist", "additional": ["categories/gcid:sports_injury_clinic", "categories/gcid:chiropractor"]}})
    patch = wire.requests[0]  # no pre-read needed: the whole set is given, and nothing is merged blindly
    assert q(patch) == {"updateMask": ["categories"]}
    assert body(patch) == {"categories": {"primaryCategory": {"name": "categories/gcid:physiotherapist"},
                                          "additionalCategories": [{"name": "categories/gcid:chiropractor"}, {"name": "categories/gcid:sports_injury_clinic"}]}}


def test_a_category_set_without_a_primary_is_refused_before_calling_google():
    p, wire = provider((200, {}))
    with pytest.raises((g.GoogleAPIError, v2f.FieldError)):
        p.update_location("AT", LOC, {"categories": {"primary": "", "additional": ["categories/gcid:x"]}})
    assert wire.requests == []


def test_after_midnight_and_midnight_closing_survive_a_read_and_a_write():
    rows = {"regularHours": {"periods": [{"openDay": "FRIDAY", "openTime": {"hours": 22}, "closeDay": "SATURDAY", "closeTime": {"hours": 2}},
                                         {"openDay": "SATURDAY", "openTime": {"hours": 9}, "closeDay": "SUNDAY", "closeTime": {}},
                                         {"openDay": "MONDAY", "openTime": {"hours": 9}, "closeDay": "MONDAY", "closeTime": {"hours": 13}},
                                         {"openDay": "MONDAY", "openTime": {"hours": 16}, "closeDay": "MONDAY", "closeTime": {"hours": 20}}]}}
    p, wire = provider((200, rows), (200, {}), (200, rows))
    d = p.get_location_details("AT", LOC)
    assert d["hours"] == [{"day": "FRIDAY", "open": "22:00", "close": "02:00+1"}, {"day": "SATURDAY", "open": "09:00", "close": "24:00"},
                          {"day": "MONDAY", "open": "09:00", "close": "13:00"}, {"day": "MONDAY", "open": "16:00", "close": "20:00"}]  # split period, after midnight, until midnight
    p.update_location("AT", LOC, {"hours": d["hours"]})
    sent = body(wire.requests[1])["regularHours"]["periods"]
    assert sent[0] == {"openDay": "FRIDAY", "openTime": {"hours": 22, "minutes": 0}, "closeDay": "SATURDAY", "closeTime": {"hours": 2, "minutes": 0}}
    assert sent[1]["closeDay"] == "SUNDAY" and sent[1]["closeTime"] == {"hours": 0, "minutes": 0}
    assert sent[2]["closeDay"] == "MONDAY" and sent[3]["openTime"] == {"hours": 16, "minutes": 0}


# ---------------------------------------------------------------- attributes
def test_attributes_are_read_and_normalised_from_googles_shape():
    p, wire = provider((200, {"name": f"{LOC}/attributes", "attributes": [{"name": "attributes/wi_fi", "valueType": "ENUM", "values": ["free_wifi"]},
                                                                          {"name": "attributes/has_x", "valueType": "BOOL", "values": [True]}]}))
    out = p.get_attributes_normalized("AT", LOC)
    assert wire.last().method == "GET" and str(wire.last().url.copy_with(query=None)) == f"{INFO}/{LOC}/attributes"
    assert out == [{"name": "attributes/has_x", "type": "BOOL", "value": True}, {"name": "attributes/wi_fi", "type": "ENUM", "value": "free_wifi"}]


def test_attribute_metadata_is_requested_for_the_location_alone_and_follows_pages():
    p, wire = provider((200, {"attributeMetadata": [{"parent": "attributes/wi_fi", "valueType": "ENUM"}], "nextPageToken": "N"}), (200, {"attributeMetadata": [{"parent": "attributes/has_x", "valueType": "BOOL"}]}))
    meta = p.attribute_metadata_for_location("AT", LOC)
    assert set(meta) == {"attributes/wi_fi", "attributes/has_x"} and len(wire.requests) == 2
    first = q(wire.requests[0])
    assert first == {"parent": [LOC], "pageSize": ["200"]}  # Google answers 400 if region/language/category are sent together with parent
    assert q(wire.requests[1])["pageToken"] == ["N"]


def test_update_attributes_sends_an_explicit_attribute_mask_and_only_what_changed():
    p, wire = provider((200, {"name": f"{LOC}/attributes", "attributes": []}))
    p.update_attributes("AT", LOC, [{"name": "attributes/wi_fi", "type": "ENUM", "value": "free_wifi"}, {"name": "attributes/pay_credit_card", "type": "REPEATED_ENUM", "value": {"set": ["visa"], "unset": []}}],
                        ["attributes/old"])
    r = wire.last()
    assert r.method == "PATCH" and str(r.url.copy_with(query=None)) == f"{INFO}/{LOC}/attributes"
    assert q(r) == {"attributeMask": ["attributes/wi_fi,attributes/pay_credit_card,attributes/old"]}
    b = body(r)
    assert b["name"] == f"{LOC}/attributes" and b["attributes"][0] == {"name": "attributes/wi_fi", "values": ["free_wifi"]}
    assert b["attributes"][1]["repeatedEnumValue"] == {"setValues": ["visa"], "unsetValues": []}
    assert all(a["name"] != "attributes/old" for a in b["attributes"])  # a deletion is a mask entry with no matching attribute


def test_update_attributes_refuses_to_send_nothing():
    p, wire = provider((200, {}))
    with pytest.raises(g.GoogleAPIError):
        p.update_attributes("AT", LOC, [], [])
    assert wire.requests == []


# ---------------------------------------------------------------- categories, Google-updated
def test_category_service_types_come_from_the_full_view_of_batchget():
    p, wire = provider((200, {"categories": [{"name": "categories/gcid:physiotherapist", "displayName": "Physiotherapist",
                                              "serviceTypes": [{"serviceTypeId": "job_type_id:dry_needling", "displayName": "Dry needling"}]}]}))
    out = p.get_category_service_types("AT", ["categories/gcid:physiotherapist"], "IN", "en")
    r = wire.last()
    assert r.method == "GET" and str(r.url.copy_with(query=None)) == f"{INFO}/categories:batchGet"
    assert q(r) == {"names": ["categories/gcid:physiotherapist"], "languageCode": ["en"], "regionCode": ["IN"], "view": ["FULL"]}  # FULL is the view that includes service types
    assert out == {"categories/gcid:physiotherapist": [{"id": "job_type_id:dry_needling", "name": "Dry needling"}]}
    assert p.get_category_service_types("AT", []) == {}


def test_google_updated_returns_only_what_differs():
    p, wire = provider((200, {"location": {"title": "x"}, "diffMask": "profile,categories", "pendingMask": "websiteUri"}))
    out = p.get_google_updated("AT", LOC, "profile,categories")
    assert str(wire.last().url.copy_with(query=None)) == f"{INFO}/{LOC}:getGoogleUpdated" and q(wire.last()) == {"readMask": ["profile,categories"]}
    assert out["diff_mask"] == "profile,categories" and out["pending_mask"] == "websiteUri"


def test_every_new_write_goes_through_the_one_patch_builder_so_validation_matches_the_write():
    """validate_changes and update_location build their request from the same function: what is dry-run is exactly what would be sent."""
    p, wire = provider((200, {}), (200, LOCATION_V2), (200, LOCATION_V2))
    changes = {"services": SERVICES}
    p.validate_changes("AT", LOC, changes)
    p.update_location("AT", LOC, changes)
    dry, real = wire.requests[0], wire.requests[1]
    assert body(dry) == body(real) and q(dry)["updateMask"] == q(real)["updateMask"] and "validateOnly" in q(dry) and "validateOnly" not in q(real)
