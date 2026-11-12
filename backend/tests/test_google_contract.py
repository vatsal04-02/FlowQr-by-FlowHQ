"""Contract tests for HttpGoogleProvider: the REAL provider code against a mock HTTP transport.

These pin the request each call sends (method, URL, query, body) and how it reads responses shaped like Google's published
reference (developers.google.com/my-business, checked 2026-11-10; see docs/GOOGLE_API_AUDIT.md). They prove the code matches
the documentation. They do NOT prove Google behaves as documented - only `python -m app.cli google-smoke` against a live,
approved project can do that.
"""
import json

import httpx
import pytest

from app.services import google as g
from app.services.google.provider import PERFORMANCE_METRICS, HttpGoogleProvider, classify_error, has_business_scope

ACCT, LOC = "accounts/1001", "locations/2002"
V4 = "https://mybusiness.googleapis.com/v4"
INFO = "https://mybusinessbusinessinformation.googleapis.com/v1"


class Wire:
    """Scripted Google: records every request, answers from a queue of (status, json) or a callable."""

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        status, body = a(request) if callable(a) else a
        if body is None:
            return httpx.Response(status)
        return httpx.Response(status, content=body) if isinstance(body, (bytes, str)) else httpx.Response(status, json=body)

    def last(self) -> httpx.Request:
        return self.requests[-1]


def provider(*answers) -> tuple[HttpGoogleProvider, Wire]:
    wire = Wire(*answers)
    return HttpGoogleProvider(transport=httpx.MockTransport(wire)), wire


def q(request: httpx.Request) -> dict:
    return {k: request.url.params.get_list(k) for k in request.url.params.keys()}


def body(request: httpx.Request) -> dict:
    return json.loads(request.content)


def error_info(reason, status="PERMISSION_DENIED", code=403, message="denied", **metadata):
    return code, {"error": {"code": code, "message": message, "status": status, "details": [
        {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason, "domain": "googleapis.com", "metadata": metadata}]}}


# ---------------------------------------------------------------- OAuth
def test_auth_url_requests_offline_access_and_only_the_business_scope():
    p, _ = provider((200, {}))
    url = httpx.URL(p.build_auth_url("STATE"))
    assert str(url).startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert url.params["access_type"] == "offline" and url.params["prompt"] == "consent" and url.params["response_type"] == "code"
    assert url.params["scope"].split() == ["openid", "email", "https://www.googleapis.com/auth/business.manage"]
    assert url.params["state"] == "STATE"


def test_token_exchange_and_refresh_use_the_documented_form_fields():
    p, wire = provider((200, {"access_token": "ya29.A", "expires_in": 3599, "refresh_token": "1//R", "scope": "openid https://www.googleapis.com/auth/business.manage", "token_type": "Bearer"}))
    ts = p.exchange_code("4/CODE")
    form = dict(httpx.QueryParams(wire.last().content.decode()))
    assert wire.last().method == "POST" and str(wire.last().url) == "https://oauth2.googleapis.com/token"
    assert form["grant_type"] == "authorization_code" and form["code"] == "4/CODE" and form["redirect_uri"] and form["client_id"] and form["client_secret"]
    assert (ts.access_token, ts.expires_in, ts.refresh_token) == ("ya29.A", 3599, "1//R") and has_business_scope(ts.scope)
    p.refresh_access_token("1//R")
    form = dict(httpx.QueryParams(wire.last().content.decode()))
    assert form["grant_type"] == "refresh_token" and form["refresh_token"] == "1//R"


def test_invalid_grant_means_reconnect_and_other_token_errors_are_not_revocations():
    p, _ = provider((400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}))
    with pytest.raises(g.GoogleAuthRevoked):
        p.refresh_access_token("1//dead")
    p, _ = provider((401, {"error": "invalid_client"}))
    with pytest.raises(g.GoogleAPIError) as e:
        p.refresh_access_token("1//R")
    assert not isinstance(e.value, g.GoogleAuthRevoked) and e.value.status == 401


def test_scope_check_accepts_only_business_scopes():
    assert has_business_scope("openid email https://www.googleapis.com/auth/business.manage")
    assert has_business_scope("https://www.googleapis.com/auth/plus.business.manage")  # deprecated alias Google still lists
    assert not has_business_scope("openid email") and not has_business_scope(None)


# ---------------------------------------------------------------- accounts / locations
def test_accounts_list_pages_with_the_maximum_page_size():
    p, wire = provider(
        (200, {"accounts": [{"name": "accounts/1001", "accountName": "Asha Sharma", "type": "PERSONAL", "role": "PRIMARY_OWNER"}], "nextPageToken": "T2"}),
        (200, {"accounts": [{"name": "accounts/1002", "accountName": "Gomti Physio Group", "type": "LOCATION_GROUP"}]}))
    accounts = p.list_accounts("AT")
    assert [(a.name, a.title) for a in accounts] == [("accounts/1001", "Asha Sharma"), ("accounts/1002", "Gomti Physio Group")]
    first, second = wire.requests
    assert first.method == "GET" and first.url.copy_with(query=None) == "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
    assert q(first) == {"pageSize": ["20"]} and q(second) == {"pageSize": ["20"], "pageToken": ["T2"]}
    assert first.headers["authorization"] == "Bearer AT"


def test_locations_list_sends_the_required_read_mask_and_reads_metadata():
    p, wire = provider((200, {"locations": [
        {"name": LOC, "title": "Gomti Physio", "storefrontAddress": {"regionCode": "IN", "addressLines": ["12 Vipin Khand"], "locality": "Lucknow", "administrativeArea": "Uttar Pradesh", "postalCode": "226010"},
         "metadata": {"placeId": "ChIJxyz", "mapsUri": "https://maps.google.com/?cid=1", "newReviewUri": "https://search.google.com/local/writereview?placeid=ChIJxyz", "hasVoiceOfMerchant": True}},
        {"name": "locations/2003", "title": "Service-area business"}]}))  # no storefrontAddress, no metadata
    locs = p.list_locations("AT", ACCT)
    r = wire.last()
    assert r.url.copy_with(query=None) == f"{INFO}/{ACCT}/locations"
    assert q(r) == {"readMask": ["name,title,storefrontAddress,metadata"], "pageSize": ["100"]}
    assert locs[0].address == "12 Vipin Khand, Lucknow, Uttar Pradesh" and locs[0].place_id == "ChIJxyz"
    assert locs[0].review_url == "https://search.google.com/local/writereview?placeid=ChIJxyz"
    assert locs[1].address is None and locs[1].review_url is None


# ---------------------------------------------------------------- reviews
REVIEWS = {"reviews": [
    {"name": f"{ACCT}/{LOC}/reviews/AbFvOq1", "reviewId": "AbFvOq1", "reviewer": {"displayName": "Ravi Kumar", "profilePhotoUrl": "https://lh3.googleusercontent.com/a/x", "isAnonymous": False},
     "starRating": "FIVE", "comment": "Very helpful staff.\n\n(Translated by Google) ...", "createTime": "2026-10-01T09:15:22.123456Z", "updateTime": "2026-10-02T10:00:00Z",
     "reviewReply": {"comment": "Thank you Ravi!", "updateTime": "2026-10-03T08:00:00Z", "reviewReplyState": "APPROVED"}},
    {"name": f"{ACCT}/{LOC}/reviews/AbFvOq2", "reviewId": "AbFvOq2", "reviewer": {"displayName": "A Google user", "isAnonymous": True},
     "starRating": "TWO", "createTime": "2026-09-01T09:00:00Z", "updateTime": "2026-09-01T09:00:00Z",  # rating-only review: no comment
     "reviewReply": {"comment": "Call us on 98xxxxxx for a discount", "updateTime": "2026-09-02T08:00:00Z", "reviewReplyState": "REJECTED", "policyViolation": "ADVERTISING_AND_SOLICITATION"}},
    {"name": f"{ACCT}/{LOC}/reviews/AbFvOq3", "reviewId": "AbFvOq3", "reviewer": {"displayName": "Meera"}, "starRating": "STAR_RATING_UNSPECIFIED",
     "createTime": "2026-08-01T09:00:00Z"}],
    "averageRating": 3.5, "totalReviewCount": 3, "nextPageToken": "NEXT"}


def test_reviews_list_request_and_every_documented_review_shape():
    p, wire = provider((200, REVIEWS))
    page = p.list_reviews("AT", ACCT, LOC, page_token="PT")
    r = wire.last()
    assert r.method == "GET" and r.url.copy_with(query=None) == f"{V4}/{ACCT}/{LOC}/reviews"
    assert q(r) == {"pageSize": ["50"], "orderBy": ["updateTime desc"], "pageToken": ["PT"]}
    a, b, c = page.reviews
    assert (a.external_id, a.rating, a.reviewer_name, a.reply_text, a.reply_state) == ("AbFvOq1", 5, "Ravi Kumar", "Thank you Ravi!", "APPROVED")
    assert (b.rating, b.text, b.reviewer_name) == (2, None, None)  # anonymous reviewers are never named
    assert b.reply_state == "REJECTED" and b.reply_policy_violation == "ADVERTISING_AND_SOLICITATION"
    assert (c.rating, c.updated_at, c.reply_text, c.reply_state) == (0, None, None, None)
    assert page.next_page_token == "NEXT"


def test_reply_is_a_put_with_only_the_comment_and_reports_googles_moderation_state():
    p, wire = provider((200, {"comment": "धन्यवाद!", "updateTime": "2026-11-10T06:00:00Z", "reviewReplyState": "PENDING"}))
    out = p.reply_to_review("AT", ACCT, LOC, "AbFvOq1", "धन्यवाद!")
    r = wire.last()
    assert r.method == "PUT" and str(r.url) == f"{V4}/{ACCT}/{LOC}/reviews/AbFvOq1/reply" and body(r) == {"comment": "धन्यवाद!"}
    assert out == {"comment": "धन्यवाद!", "updated_at": "2026-11-10T06:00:00Z", "state": "PENDING", "policy_violation": None}


def test_reply_over_4096_bytes_is_refused_before_calling_google():
    p, wire = provider((200, {}))
    with pytest.raises(g.GoogleAPIError):
        p.reply_to_review("AT", ACCT, LOC, "r1", "ध" * 1400)  # 1400 chars but 4200 bytes
    assert wire.requests == []


# ---------------------------------------------------------------- business information
LOCATION = {"name": LOC, "title": "Gomti Physio", "phoneNumbers": {"primaryPhone": "+91 98765 43210", "additionalPhones": ["0522 400 1234"]},
            "categories": {"primaryCategory": {"name": "categories/gcid:physiotherapist", "displayName": "Physiotherapist"},
                           "additionalCategories": [{"name": "categories/gcid:sports_massage_therapist", "displayName": "Sports massage therapist"}]},
            "websiteUri": "https://gomtiphysio.example.in/", "profile": {"description": "Physiotherapy clinic in Gomti Nagar."},
            "regularHours": {"periods": [{"openDay": "MONDAY", "openTime": {"hours": 9}, "closeDay": "MONDAY", "closeTime": {"hours": 18, "minutes": 30}},
                                         {"openDay": "SUNDAY", "openTime": {}, "closeDay": "SUNDAY", "closeTime": {"hours": 24}}]}}


def test_location_get_sends_read_mask_and_handles_omitted_zero_times():
    p, wire = provider((200, LOCATION))
    d = p.get_location_details("AT", LOC)
    assert wire.last().url.copy_with(query=None) == f"{INFO}/{LOC}" and "readMask" in q(wire.last())
    assert d["phone"] == "+91 98765 43210" and d["primary_category"] == {"id": "categories/gcid:physiotherapist", "name": "Physiotherapist"}
    assert d["hours"] == [{"day": "MONDAY", "open": "09:00", "close": "18:30"}, {"day": "SUNDAY", "open": "00:00", "close": "24:00"}]


def test_changing_the_phone_keeps_additional_phones_because_google_replaces_the_whole_object():
    p, wire = provider((200, {"phoneNumbers": LOCATION["phoneNumbers"]}), (200, LOCATION), (200, LOCATION))
    p.update_location("AT", LOC, {"phone": "+91 90000 00000"})
    read, patch, _ = wire.requests
    assert read.method == "GET" and q(read) == {"readMask": ["phoneNumbers"]}
    assert patch.method == "PATCH" and patch.url.copy_with(query=None) == f"{INFO}/{LOC}" and q(patch) == {"updateMask": ["phoneNumbers"]}
    assert body(patch) == {"phoneNumbers": {"primaryPhone": "+91 90000 00000", "additionalPhones": ["0522 400 1234"]}}


def test_changing_additional_categories_keeps_the_primary_category():
    p, wire = provider((200, {"categories": LOCATION["categories"]}), (200, LOCATION), (200, LOCATION))
    p.update_location("AT", LOC, {"additional_categories": ["categories/gcid:chiropractor"]})
    patch = wire.requests[1]
    assert q(patch) == {"updateMask": ["categories"]}
    assert body(patch) == {"categories": {"primaryCategory": {"name": "categories/gcid:physiotherapist"}, "additionalCategories": [{"name": "categories/gcid:chiropractor"}]}}


def test_description_hours_and_website_patch_uses_one_mask_and_no_extra_read():
    p, wire = provider((200, LOCATION))
    p.update_location("AT", LOC, {"description": "New text", "website": "https://x.example.in", "hours": [{"day": "TUESDAY", "open": "09:00", "close": "17:30"}]})
    patch = wire.requests[0]
    assert patch.method == "PATCH" and q(patch) == {"updateMask": ["profile,regularHours,websiteUri"]}
    assert body(patch) == {"profile": {"description": "New text"}, "websiteUri": "https://x.example.in",
                           "regularHours": {"periods": [{"openDay": "TUESDAY", "openTime": {"hours": 9, "minutes": 0}, "closeDay": "TUESDAY", "closeTime": {"hours": 17, "minutes": 30}}]}}


def test_category_search_sends_all_three_required_params_and_the_documented_filter():
    p, wire = provider((200, {"categories": [{"name": "categories/gcid:dentist", "displayName": "Dentist"}], "nextPageToken": "x"}))
    assert p.search_categories("AT", 'dent"=ist') == [{"id": "categories/gcid:dentist", "name": "Dentist"}]
    assert wire.last().url.copy_with(query=None) == f"{INFO}/categories"
    assert q(wire.last()) == {"regionCode": ["IN"], "languageCode": ["en"], "view": ["BASIC"], "pageSize": ["20"], "filter": ["displayName=dentist"]}


# ---------------------------------------------------------------- local posts
POST = {"name": f"{ACCT}/{LOC}/localPosts/777", "languageCode": "en", "summary": "Diwali offer week", "state": "LIVE", "topicType": "STANDARD",
        "createTime": "2026-11-01T05:00:00Z", "updateTime": "2026-11-01T05:00:00Z", "searchUrl": "https://local.google.com/place?id=1&use=posts&lpsid=777",
        "callToAction": {"actionType": "LEARN_MORE", "url": "https://gomtiphysio.example.in/diwali"},
        "media": [{"name": f"{ACCT}/{LOC}/media/localPosts/AF1Q", "mediaFormat": "PHOTO", "googleUrl": "https://lh3.googleusercontent.com/p/AF1Q"}]}


def test_post_create_body_matches_the_local_post_resource():
    p, wire = provider((200, POST))
    out = p.create_post("AT", ACCT, LOC, {"summary": "Diwali offer week", "language": "en", "cta_type": "LEARN_MORE", "cta_url": "https://gomtiphysio.example.in/diwali",
                                          "photo_url": "https://cdn.example.in/diwali.jpg"})
    r = wire.last()
    assert r.method == "POST" and str(r.url) == f"{V4}/{ACCT}/{LOC}/localPosts"
    assert body(r) == {"languageCode": "en", "summary": "Diwali offer week", "topicType": "STANDARD",
                       "callToAction": {"actionType": "LEARN_MORE", "url": "https://gomtiphysio.example.in/diwali"},
                       "media": [{"mediaFormat": "PHOTO", "sourceUrl": "https://cdn.example.in/diwali.jpg"}]}
    assert out["name"].endswith("/localPosts/777") and out["state"] == "LIVE" and out["cta_type"] == "LEARN_MORE"
    assert out["photo_url"] == "https://lh3.googleusercontent.com/p/AF1Q" and out["search_url"].startswith("https://local.google.com/")


def test_call_button_never_carries_a_url():
    p, wire = provider((200, POST))
    p.create_post("AT", ACCT, LOC, {"summary": "Call us today for a slot", "cta_type": "CALL", "cta_url": "https://ignored.example"})
    assert body(wire.last())["callToAction"] == {"actionType": "CALL"}


def test_post_edit_is_a_patch_with_an_update_mask_and_can_remove_the_button():
    p, wire = provider((200, POST))
    p.update_post("AT", POST["name"], {"summary": "Now until Sunday"})
    r = wire.last()
    assert r.method == "PATCH" and r.url.copy_with(query=None) == f"{V4}/{POST['name']}" and q(r) == {"updateMask": ["summary"]}
    assert body(r) == {"summary": "Now until Sunday"}
    p.update_post("AT", POST["name"], {"summary": "Now until Sunday", "cta_type": None, "cta_url": None})
    assert q(wire.last()) == {"updateMask": ["summary,callToAction"]} and body(wire.last()) == {"summary": "Now until Sunday"}


def test_post_list_pages_and_delete_expects_an_empty_body():
    p, wire = provider((200, {"localPosts": [POST], "nextPageToken": "N"}), (200, {"localPosts": [{**POST, "name": POST["name"] + "8", "state": "REJECTED"}]}))
    posts = p.list_posts("AT", ACCT, LOC)
    assert [x["state"] for x in posts] == ["LIVE", "REJECTED"]
    assert q(wire.requests[0]) == {"pageSize": ["100"]} and q(wire.requests[1]) == {"pageSize": ["100"], "pageToken": ["N"]}
    p, wire = provider((200, None))
    assert p.delete_post("AT", POST["name"]) is None
    assert wire.last().method == "DELETE" and str(wire.last().url) == f"{V4}/{POST['name']}"


# ---------------------------------------------------------------- media
def test_media_create_and_list_and_logo_alias():
    item = {"name": f"{ACCT}/{LOC}/media/AF1QipN", "mediaFormat": "PHOTO", "locationAssociation": {"category": "EXTERIOR"},
            "googleUrl": "https://lh3.googleusercontent.com/p/AF1QipN", "thumbnailUrl": "https://lh3.googleusercontent.com/p/AF1QipN=s300", "createTime": "2026-10-05T07:00:00Z"}
    p, wire = provider((200, item))
    out = p.add_media("AT", ACCT, LOC, "https://cdn.example.in/front.jpg", "EXTERIOR")
    assert wire.last().method == "POST" and str(wire.last().url) == f"{V4}/{ACCT}/{LOC}/media"
    assert body(wire.last()) == {"mediaFormat": "PHOTO", "sourceUrl": "https://cdn.example.in/front.jpg", "locationAssociation": {"category": "EXTERIOR"}}
    assert out == {"name": item["name"], "category": "EXTERIOR", "url": item["googleUrl"], "thumbnail": item["thumbnailUrl"], "created_at": item["createTime"]}
    p.add_media("AT", ACCT, LOC, "https://cdn.example.in/logo.png", "LOGO")
    assert body(wire.last())["locationAssociation"] == {"category": "PROFILE"}  # LOGO is deprecated in favour of PROFILE
    p, wire = provider((200, {"mediaItems": [item], "totalMediaItemCount": 1}))
    assert len(p.list_media("AT", ACCT, LOC)) == 1 and q(wire.last()) == {"pageSize": ["100"]}


# ---------------------------------------------------------------- performance
def test_performance_request_matches_the_reference_example_and_sends_no_retired_metric():
    p, wire = provider((200, {}))
    assert p.fetch_performance("AT", LOC, "2026-10-01", "2026-10-31", PERFORMANCE_METRICS) == {}
    r = wire.last()
    assert r.method == "GET" and r.url.copy_with(query=None) == f"https://businessprofileperformance.googleapis.com/v1/{LOC}:fetchMultiDailyMetricsTimeSeries"
    params = q(r)
    assert params.pop("dailyMetrics") == PERFORMANCE_METRICS
    assert params == {"dailyRange.start_date.year": ["2026"], "dailyRange.start_date.month": ["10"], "dailyRange.start_date.day": ["1"],
                      "dailyRange.end_date.year": ["2026"], "dailyRange.end_date.month": ["10"], "dailyRange.end_date.day": ["31"]}
    assert "BUSINESS_CONVERSATIONS" not in PERFORMANCE_METRICS and "BUSINESS_FOOD_ORDERS" not in PERFORMANCE_METRICS  # deprecated by Google
    assert "MESSAGING_CLICKS" in PERFORMANCE_METRICS and "DAILY_METRIC_UNKNOWN" not in PERFORMANCE_METRICS


def test_performance_response_string_values_missing_zeros_and_sub_entity_breakdowns():
    day = lambda d, v=None: {"date": {"year": 2026, "month": 10, "day": d}, **({"value": v} if v is not None else {})}  # noqa: E731
    p, _ = provider((200, {"multiDailyMetricTimeSeries": [{"dailyMetricTimeSeries": [
        {"dailyMetric": "CALL_CLICKS", "timeSeries": {"datedValues": [day(1, "3"), day(2), day(3, "12")]}},  # day 2: value omitted == 0
        {"dailyMetric": "BUSINESS_BOOKINGS", "dailySubEntityType": {"dayOfWeek": "MONDAY"}, "timeSeries": {"datedValues": [day(1, "1")]}},
        {"dailyMetric": "BUSINESS_BOOKINGS", "dailySubEntityType": {"dayOfWeek": "TUESDAY"}, "timeSeries": {"datedValues": [day(1, "2")]}},
        {"dailyMetric": "WEBSITE_CLICKS", "timeSeries": {}}]}]}))
    out = p.fetch_performance("AT", LOC, "2026-10-01", "2026-10-03", ["CALL_CLICKS"])
    assert out["CALL_CLICKS"] == [{"date": "2026-10-01", "value": 3}, {"date": "2026-10-02", "value": 0}, {"date": "2026-10-03", "value": 12}]
    assert out["BUSINESS_BOOKINGS"] == [{"date": "2026-10-01", "value": 3}] and out["WEBSITE_CLICKS"] == []


# ---------------------------------------------------------------- errors: never a fake success
def test_api_not_enabled_is_reported_as_such_with_the_service_name():
    p, _ = provider(error_info("SERVICE_DISABLED", message="My Business Account Management API has not been used in project 123 before or it is disabled.",
                               consumer="projects/123", service="mybusinessaccountmanagement.googleapis.com"))
    with pytest.raises(g.GoogleApiNotApproved) as e:
        p.list_accounts("AT")
    assert e.value.why == "service_disabled" and e.value.service == "mybusinessaccountmanagement.googleapis.com" and not e.value.transient


def test_quota_errors_rate_limit_unless_google_says_the_limit_is_zero():
    limited = error_info("RATE_LIMIT_EXCEEDED", status="RESOURCE_EXHAUSTED", code=429, message="Quota exceeded for quota metric 'Requests' and limit 'Requests per minute'",
                         consumer="projects/123", service="mybusiness.googleapis.com", quota_metric="mybusiness.googleapis.com/default_requests", quota_limit="DefaultRequestsPerMinutePerProject")
    p, _ = provider(limited)
    with pytest.raises(g.GoogleRateLimited) as e:
        p.list_reviews("AT", ACCT, LOC)
    assert e.value.quota_metric == "mybusiness.googleapis.com/default_requests"
    zero = (429, {"error": {**limited[1]["error"], "details": [{**limited[1]["error"]["details"][0], "metadata": {**limited[1]["error"]["details"][0]["metadata"], "quota_limit_value": "0"}}]}})
    p, _ = provider(zero)
    with pytest.raises(g.GoogleApiNotApproved) as e2:
        p.list_reviews("AT", ACCT, LOC)
    assert e2.value.why == "quota_zero"
    assert isinstance(classify_error(429, None, "17"), g.GoogleRateLimited) and classify_error(429, None, "17").retry_after == 17  # bare 429


@pytest.mark.parametrize("answer, expected", [
    (error_info("ACCESS_TOKEN_SCOPE_INSUFFICIENT", message="Request had insufficient authentication scopes.", service="mybusiness.googleapis.com"), g.GoogleScopeMissing),
    ((401, {"error": {"code": 401, "message": "Request had invalid authentication credentials.", "status": "UNAUTHENTICATED"}}), g.GoogleAuthRevoked),
])
def test_auth_problems_ask_for_a_reconnect(answer, expected):
    p, _ = provider(answer)
    with pytest.raises(expected):
        p.list_accounts("AT")


def test_permission_not_found_invalid_and_server_errors_keep_googles_status_and_message():
    p, _ = provider((403, {"error": {"code": 403, "message": "The caller does not have permission", "status": "PERMISSION_DENIED"}}))
    with pytest.raises(g.GoogleAPIError) as e:
        p.list_reviews("AT", ACCT, LOC)
    assert type(e.value) is g.GoogleAPIError and e.value.status == 403 and e.value.google_status == "PERMISSION_DENIED" and not e.value.transient
    p, _ = provider((400, {"error": {"code": 400, "message": "Request contains an invalid argument.", "status": "INVALID_ARGUMENT"}}))
    with pytest.raises(g.GoogleAPIError) as e:
        p.create_post("AT", ACCT, LOC, {"summary": "x" * 20})
    assert e.value.status == 400 and "invalid argument" in str(e.value)
    p, _ = provider((404, {"error": {"code": 404, "message": "Requested entity was not found.", "status": "NOT_FOUND"}}))
    with pytest.raises(g.GoogleAPIError) as e:
        p.delete_post("AT", POST["name"])
    assert e.value.status == 404
    p, _ = provider((503, "<html>Service Unavailable</html>"))
    with pytest.raises(g.GoogleAPIError) as e:
        p.list_accounts("AT")
    assert e.value.status == 503 and e.value.transient


def test_a_200_that_is_not_json_and_a_dropped_connection_are_failures():
    p, _ = provider((200, "<html>captive portal</html>"))
    with pytest.raises(g.GoogleAPIError):
        p.list_accounts("AT")

    def boom(request):
        raise httpx.ConnectError("no route", request=request)
    p = HttpGoogleProvider(transport=httpx.MockTransport(boom))
    with pytest.raises(g.GoogleAPIError) as e:
        p.reply_to_review("AT", ACCT, LOC, "r1", "Thanks")
    assert e.value.status == 503 and e.value.transient


def test_smoke_command_makes_no_call_and_says_so_without_credentials(monkeypatch, capsys):
    from app.services.google import smoke as google_smoke
    from app.core.config import settings

    monkeypatch.delenv("GOOGLE_SMOKE_REFRESH_TOKEN", raising=False)
    assert google_smoke.main([]) == 2 and "No Google call was made" in capsys.readouterr().out
    monkeypatch.setattr(settings, "google_client_id", "")
    assert google_smoke.main([]) == 2 and "BLOCKED" in capsys.readouterr().out


def test_smoke_command_is_read_only_and_reports_an_unapproved_project(monkeypatch, capsys):
    from app.services.google import smoke as google_smoke

    seen = []

    def google(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.host))
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "ya29.A", "expires_in": 3599, "scope": "https://www.googleapis.com/auth/business.manage"})
        status, payload = error_info("SERVICE_DISABLED", service=request.url.host)
        return httpx.Response(status, json=payload)
    monkeypatch.setenv("GOOGLE_SMOKE_REFRESH_TOKEN", "1//R")
    monkeypatch.setattr(g, "get_google_provider", lambda: HttpGoogleProvider(transport=httpx.MockTransport(google)))
    assert google_smoke.main([]) == 3
    out = capsys.readouterr().out
    assert "NOT APPROVED" in out and "1//R" not in out and "ya29.A" not in out
    assert {m for m, _ in seen} <= {"GET", "POST"} and [h for m, h in seen if m == "POST"] == ["oauth2.googleapis.com"]


# ---------------------------------------------------------------- real Google responses
# The bodies below are NOT written from documentation: they were returned by the live APIs on 2026-11-10 for a real OAuth
# token on a Cloud project where the Business Profile APIs are not enabled (project number replaced by 000000000000).
# They are the only part of this file that is verified against Google itself.
def _live_disabled(title: str, service: str) -> tuple[int, dict]:
    activation = f"https://console.developers.google.com/apis/api/{service}/overview?project=000000000000"
    return 403, {"error": {"code": 403, "status": "PERMISSION_DENIED",
                           "message": f"{title} has not been used in project 000000000000 before or it is disabled. Enable it by visiting {activation} then retry. "
                                      "If you enabled this API recently, wait a few minutes for the action to propagate to our systems and retry.",
                           "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "SERVICE_DISABLED", "domain": "googleapis.com",
                                        "metadata": {"service": service, "serviceTitle": title, "consumer": "projects/000000000000",
                                                     "containerInfo": "000000000000", "activationUrl": activation}}]}}


@pytest.mark.parametrize("title, service, call", [
    ("My Business Account Management API", "mybusinessaccountmanagement.googleapis.com", lambda p: p.list_accounts("AT")),
    ("My Business Business Information API", "mybusinessbusinessinformation.googleapis.com", lambda p: p.list_locations("AT", ACCT)),
    ("My Business Business Information API", "mybusinessbusinessinformation.googleapis.com", lambda p: p.search_categories("AT", "dent")),
    ("Google My Business API", "mybusiness.googleapis.com", lambda p: p.list_reviews("AT", ACCT, LOC)),
    ("Google My Business API", "mybusiness.googleapis.com", lambda p: p.list_posts("AT", ACCT, LOC)),
    ("Business Profile Performance API", "businessprofileperformance.googleapis.com", lambda p: p.fetch_performance("AT", LOC, "2026-10-01", "2026-10-02", ["CALL_CLICKS"])),
])
def test_the_error_google_really_returns_for_a_disabled_api_names_that_api(title, service, call):
    p, _ = provider(_live_disabled(title, service))
    with pytest.raises(g.GoogleApiNotApproved) as e:
        call(p)
    assert e.value.why == "service_disabled" and e.value.service == service and e.value.status == 403 and not e.value.transient
    assert service in str(e.value)
