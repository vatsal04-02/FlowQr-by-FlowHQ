"""Website hosting providers: a publish is atomic for the public (files first, pointer last), a failure leaves the previous version live, credentials never leak, and the request signing is correct.
The Cloudflare provider is tested against an in-memory R2 and Workers KV (httpx MockTransport); no network is used."""
import hashlib
import json
import logging
import re

import httpx
import pytest

from app.core.config import settings
from app.services.sites import hosting
from app.services.sites.hosting import CloudflareProvider, HostingError, LocalDirectoryProvider, sign_v4

SID = "11111111-2222-3333-4444-555555555555"
HOST = "sharma.flowqr.site"
TOKEN, AK, SK, ACCT = "cf-api-token-SECRET-123", "r2accesskeyid0001", "r2secretaccesskey-SECRET-xyz", "acct0123456789"


def files(tag="one"):
    return {"index.html": f"<html>{tag}</html>".encode(), "privacy/index.html": b"<html>privacy</html>", "style.abc.css": b"body{}", "assets/aaaa.webp": b"RIFFxxxxWEBPyyyy", "robots.txt": b"User-agent: *"}


# ---------------------------------------------------------------------------------------------------------------- an in-memory Cloudflare
class FakeCloudflare:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.kv: dict[str, str] = {}
        self.log: list[tuple[str, str]] = []  # (kind, detail) in order
        self.requests: list[httpx.Request] = []
        self.fail_put_after: int | None = None  # every R2 PUT after this many succeed-ones is a 503
        self.fail_kv_put = False
        self.flaky_once: set[str] = set()  # keys whose first PUT is a 503 (then ok)
        self.bad_etag = False
        self.puts = 0

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        url = req.url
        if url.host.endswith("r2.cloudflarestorage.com"):
            path = url.path.lstrip("/").split("/", 1)
            key = path[1] if len(path) > 1 else ""
            if req.method == "PUT":
                if key in self.flaky_once:
                    self.flaky_once.discard(key)
                    self.log.append(("r2-503", key))
                    return httpx.Response(503)
                if self.fail_put_after is not None and self.puts >= self.fail_put_after:
                    self.log.append(("r2-fail", key))
                    return httpx.Response(503)
                self.puts += 1
                self.objects[key] = req.content
                self.log.append(("r2-put", key))
                return httpx.Response(200, headers={"ETag": '"' + ("0" * 32 if self.bad_etag else hashlib.md5(req.content).hexdigest()) + '"'})
            if req.method == "DELETE":
                self.objects.pop(key, None)
                self.log.append(("r2-delete", key))
                return httpx.Response(204)
            if req.method == "GET":
                prefix = dict(url.params).get("prefix", "")
                keys = sorted(k for k in self.objects if k.startswith(prefix))
                body = '<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">' + "".join(f"<Contents><Key>{k}</Key></Contents>" for k in keys) + "</ListBucketResult>"
                return httpx.Response(200, content=body.encode())
        if url.host == "api.cloudflare.com":
            if "/storage/kv/" in url.path:
                key = url.path.split("/values/", 1)[1].replace("%3A", ":")
                if req.method == "PUT":
                    if self.fail_kv_put:
                        self.log.append(("kv-fail", key))
                        return httpx.Response(500)
                    self.kv[key] = req.content.decode()
                    self.log.append(("kv-put", key))
                    return httpx.Response(200, json={"success": True})
                if req.method == "DELETE":
                    existed = self.kv.pop(key, None) is not None
                    self.log.append(("kv-delete", key))
                    return httpx.Response(200 if existed else 404, json={"success": existed})
                if req.method == "GET":
                    return httpx.Response(200, content=self.kv[key].encode()) if key in self.kv else httpx.Response(404)
            if url.path.endswith("/purge_cache"):
                self.log.append(("purge", ""))
                return httpx.Response(200, json={"success": True})
        return httpx.Response(404)

    def provider(self, **kw) -> CloudflareProvider:
        return CloudflareProvider(account_id=ACCT, api_token=TOKEN, kv_namespace_id="kvns", bucket="sites-bucket", access_key_id=AK, secret_access_key=SK, zone_id=kw.pop("zone_id", ""),
                                  client=httpx.Client(transport=httpx.MockTransport(self.handler)), sleep=lambda s: None, **kw)


@pytest.fixture()
def cf():
    return FakeCloudflare()


# ---------------------------------------------------------------------------------------------------------------- Cloudflare provider
def test_files_are_stored_first_and_the_hostname_is_switched_last(cf):
    r = cf.provider().publish_site(SID, HOST, files(), 1)
    kinds = [k for k, _ in cf.log]
    assert r.version == 1 and r.files == 5 and r.bytes == sum(len(v) for v in files().values())
    first_kv = kinds.index("kv-put")
    assert kinds[:first_kv] and all(k == "r2-put" for k in kinds[:first_kv]) and kinds.count("r2-put") == 5, kinds  # every file was stored before the hostname was switched
    assert sorted(k for k in cf.objects) == sorted(f"sites/{SID}/v1/{p}" for p in files())
    assert json.loads(cf.kv[f"host:{HOST}"]) == {"site_id": SID, "version": 1, "status": "published"}


def test_content_types_are_set_and_no_object_lands_outside_the_sites_prefix(cf):
    cf.provider().publish_site(SID, HOST, files(), 1)
    ct = {r.url.path.split("/", 2)[2]: r.headers.get("content-type") for r in cf.requests if r.method == "PUT" and "r2.cloudflarestorage" in r.url.host}
    assert ct[f"sites/{SID}/v1/index.html"] == "text/html; charset=utf-8" and ct[f"sites/{SID}/v1/assets/aaaa.webp"] == "image/webp" and ct[f"sites/{SID}/v1/style.abc.css"].startswith("text/css")
    assert all(k.startswith(f"sites/{SID}/") for k in cf.objects)


def test_a_failed_upload_leaves_the_previous_version_live(cf):
    p = cf.provider()
    p.publish_site(SID, HOST, files("one"), 1)
    before = dict(cf.kv)
    cf.fail_put_after = cf.puts + 2  # the third file of version 2 fails, on every retry
    with pytest.raises(HostingError) as e:
        p.publish_site(SID, HOST, files("two"), 2)
    assert e.value.retryable and e.value.code in ("upload_failed", "provider_error")
    assert cf.kv == before and json.loads(cf.kv[f"host:{HOST}"])["version"] == 1, "the hostname was switched although the upload failed"
    assert cf.objects[f"sites/{SID}/v1/index.html"] == b"<html>one</html>"  # version 1 is intact and still what the pointer names


def test_a_failed_pointer_switch_is_reported_and_the_previous_version_stays(cf):
    p = cf.provider()
    p.publish_site(SID, HOST, files("one"), 1)
    cf.fail_kv_put = True
    with pytest.raises(HostingError) as e:
        p.publish_site(SID, HOST, files("two"), 2)
    assert e.value.code == "pointer_failed" and "previous version is still live" in str(e.value)
    assert json.loads(cf.kv[f"host:{HOST}"])["version"] == 1


def test_transient_provider_errors_are_retried(cf):
    cf.flaky_once.add(f"sites/{SID}/v1/index.html")
    r = cf.provider().publish_site(SID, HOST, files(), 1)
    assert r.version == 1 and ("r2-503", f"sites/{SID}/v1/index.html") in cf.log and f"sites/{SID}/v1/index.html" in cf.objects


def test_an_object_that_was_not_stored_intact_is_not_published(cf):
    cf.bad_etag = True
    with pytest.raises(HostingError) as e:
        cf.provider().publish_site(SID, HOST, files(), 1)
    assert e.value.code == "upload_corrupt" and f"host:{HOST}" not in cf.kv


def test_credentials_never_appear_in_errors_or_logs(cf, caplog):
    caplog.set_level(logging.DEBUG)
    cf.fail_put_after = 1
    with pytest.raises(HostingError) as e:
        cf.provider().publish_site(SID, HOST, files(), 1)
    text = str(e.value) + repr(e.value.args) + caplog.text
    for secret in (TOKEN, SK, AK, "SECRET"):
        assert secret not in text, secret


def test_r2_requests_are_signed_and_the_secret_is_never_sent(cf):
    cf.provider().publish_site(SID, HOST, files(), 1)
    puts = [r for r in cf.requests if r.method == "PUT" and "r2.cloudflarestorage" in r.url.host]
    assert puts
    for r in puts:
        auth = r.headers["authorization"]
        assert auth.startswith("AWS4-HMAC-SHA256 Credential=" + AK + "/") and "/auto/s3/aws4_request" in auth and "Signature=" in auth
        assert r.headers["x-amz-content-sha256"] == hashlib.sha256(r.content).hexdigest()
        assert SK not in str(r.headers) and TOKEN not in str(r.headers)
    kv = [r for r in cf.requests if r.url.host == "api.cloudflare.com"][0]
    assert kv.headers["authorization"] == f"Bearer {TOKEN}" and AK not in str(kv.headers)


def test_old_versions_are_cleaned_up_but_the_last_two_are_kept_for_rollback(cf):
    p = cf.provider()
    for v in (1, 2, 3):
        p.publish_site(SID, HOST, files(f"v{v}"), v)
    versions = {k.split("/")[2] for k in cf.objects}
    assert versions == {"v2", "v3"} and json.loads(cf.kv[f"host:{HOST}"])["version"] == 3


def test_unpublish_removes_the_pointer_and_keeps_the_files(cf):
    p = cf.provider()
    p.publish_site(SID, HOST, files(), 1)
    p.unpublish_site(SID, HOST)
    assert f"host:{HOST}" not in cf.kv and p.resolve_site_hostname(HOST) is None and len(cf.objects) == 5
    p.unpublish_site(SID, HOST)  # idempotent: a missing pointer is not an error


def test_suspend_and_resume_change_only_the_pointer(cf):
    p = cf.provider()
    p.publish_site(SID, HOST, files(), 1)
    puts = cf.puts
    p.set_status(SID, HOST, 1, "suspended")
    assert json.loads(cf.kv[f"host:{HOST}"]) == {"site_id": SID, "version": 1, "status": "suspended"} and cf.puts == puts
    assert p.get_publish_status(SID, HOST)["status"] == "suspended" and p.get_publish_status("other-site", HOST) is None


def test_delete_removes_every_pointer_and_every_file_of_that_site_only(cf):
    p = cf.provider()
    p.publish_site(SID, HOST, files(), 1)
    p.publish_site("99999999-0000-0000-0000-000000000000", "other.flowqr.site", files("o"), 1)
    p.delete_site(SID, [HOST])
    assert f"host:{HOST}" not in cf.kv and "host:other.flowqr.site" in cf.kv
    assert not any(k.startswith(f"sites/{SID}/") for k in cf.objects) and any(k.startswith("sites/99999999") for k in cf.objects)


def test_cache_purge_is_best_effort_and_only_when_a_zone_is_configured(cf):
    cf.provider().publish_site(SID, HOST, files(), 1)
    assert ("purge", "") not in cf.log
    cf.provider(zone_id="zone1").publish_site(SID, HOST, files(), 2)
    assert ("purge", "") in cf.log


def test_an_unconfigured_provider_says_so():
    assert not CloudflareProvider(account_id="", api_token="", kv_namespace_id="", bucket="", access_key_id="", secret_access_key="").configured()


def test_aws_signature_v4_matches_the_published_test_vector():
    """AWS's documentation example: GET /test.txt with a Range header. Also cross-checked against botocore for PUT, GET (list) and DELETE when this was written."""
    h = hashlib.sha256(b"").hexdigest()
    out = sign_v4("GET", "examplebucket.s3.amazonaws.com", "/test.txt", "", {"Range": "bytes=0-9"}, h, "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "us-east-1", "s3", "20130524T000000Z")
    assert out["Authorization"].endswith("Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")
    assert "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date" in out["Authorization"]


def test_the_content_security_policy_forbids_scripts_inline_styles_and_framing():
    csp = hosting.CSP
    assert "script-src 'none'" in csp and "default-src 'none'" in csp and "frame-ancestors 'none'" in csp and "form-action 'self'" in csp and "base-uri 'none'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp and "*" not in csp and "http:" not in csp


# ---------------------------------------------------------------------------------------------------------------- local provider
def test_local_publish_serves_the_new_version_only_after_every_file_is_written(tmp_path):
    p = LocalDirectoryProvider(tmp_path)
    p.publish_site(SID, HOST, files("one"), 1)
    assert p.read(HOST) == b"<html>one</html>" and p.read(HOST, "privacy/index.html") == b"<html>privacy</html>" and p.read(HOST, "nope.html") is None
    p.fail_after = 2
    with pytest.raises(HostingError):
        p.publish_site(SID, HOST, files("two"), 2)
    assert p.read(HOST) == b"<html>one</html>", "a failed publish changed what the public sees"
    p.fail_after = None
    p.publish_site(SID, HOST, files("two"), 2)
    assert p.read(HOST) == b"<html>two</html>"


def test_local_versions_are_pruned_and_status_and_unpublish_work(tmp_path):
    p = LocalDirectoryProvider(tmp_path)
    for v in (1, 2, 3):
        p.publish_site(SID, HOST, files(f"v{v}"), v)
    assert sorted(d.name for d in (tmp_path / "sites" / SID).iterdir()) == ["v2", "v3"]
    p.set_status(SID, HOST, 3, "suspended")
    assert p.read(HOST) is None and p.resolve_site_hostname(HOST)["status"] == "suspended"
    p.set_status(SID, HOST, 3, "published")
    assert p.read(HOST) == b"<html>v3</html>"
    p.unpublish_site(SID, HOST)
    assert p.read(HOST) is None and p.resolve_site_hostname(HOST) is None and (tmp_path / "sites" / SID / "v3").exists()
    p.delete_site(SID, [HOST])
    assert not (tmp_path / "sites" / SID).exists()


def test_provider_selection_follows_the_settings(monkeypatch, tmp_path):
    hosting.set_provider(None)
    monkeypatch.setattr(settings, "sites_provider", "local")
    monkeypatch.setattr(settings, "sites_local_dir", str(tmp_path))
    assert isinstance(hosting.get_hosting_provider(), LocalDirectoryProvider)
    monkeypatch.setattr(settings, "sites_provider", "cloudflare")
    p = hosting.get_hosting_provider()
    assert isinstance(p, CloudflareProvider) and not p.configured()  # nothing is configured in tests, and it says so instead of guessing
