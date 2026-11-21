"""Where a published website lives.

`HostingProvider` is the seam: the rest of FlowQR (service.py, the admin API) only ever calls these methods, so the website generator is not tied to one host. Two providers:

  * LocalDirectoryProvider  writes the files to a folder. Development and tests only (config refuses it in production).
  * CloudflareProvider      R2 holds the static files, one Workers KV entry per hostname points at the live version, and ONE shared Worker (deploy/cloudflare/sites-worker) serves every
                            business from them. No deployment per customer, no project per customer.

PUBLISH IS ATOMIC FROM THE PUBLIC'S POINT OF VIEW. Every file of the new version is uploaded under its own versioned prefix first (sites/<site id>/v<n>/...). Only when ALL of them are stored (and
their checksums match) is the hostname's pointer switched to the new version. If anything fails before that, the pointer is untouched and the previous version keeps being served. Old versions are
kept (the last two) so a rollback is a pointer change. Credentials come from server-side settings only; they are never put in a message, a log line, or an API response."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.services.sites import render

log = logging.getLogger("flowqr.sites.hosting")
MAX_LIST_XML_BYTES = 5 * 1024 * 1024  # an R2 object listing answer is far smaller than this

# The Content-Security-Policy every business website is served with. Pages ship no JavaScript, so scripts are refused outright; styles and images come only from the site itself; the one form
# posts back to the site itself. The Worker sends exactly this (tests/test_sites_hosting.py compares the two so they cannot drift apart).
CSP = "default-src 'none'; script-src 'none'; style-src 'self'; img-src 'self'; font-src 'none'; connect-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
KEEP_VERSIONS = 2
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".webp": "image/webp", ".txt": "text/plain; charset=utf-8", ".xml": "application/xml; charset=utf-8",
                 ".json": "application/json", ".svg": "image/svg+xml"}


class HostingError(Exception):
    """A hosting failure with a message that is safe to show an administrator (no URLs with credentials, no tokens)."""

    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code, self.retryable = code, retryable


@dataclass
class PublishResult:
    version: int
    files: int
    bytes: int


def content_type_for(path: str) -> str:
    return CONTENT_TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


def pointer(site_id: str, version: int, status: str = "published") -> dict:
    return {"site_id": site_id, "version": version, "status": status}


class HostingProvider(ABC):
    name = "abstract"

    def configured(self) -> bool:
        return True

    # ---- generation is the same for every provider: a provider only stores what the renderer produced
    def build_site(self, content: dict, template_key: str, *, host: str, assets: dict, retention_days: int) -> dict[str, bytes]:
        return render.build_site(content, template_key, host=host, assets=assets, retention_days=retention_days)

    @abstractmethod
    def publish_site(self, site_id: str, host: str, files: dict[str, bytes], version: int) -> PublishResult: ...

    @abstractmethod
    def set_status(self, site_id: str, host: str, version: int, status: str) -> None:
        """Point the hostname at an existing version as 'published' or 'suspended' without uploading anything."""

    @abstractmethod
    def unpublish_site(self, site_id: str, host: str) -> None:
        """The hostname stops resolving. The files are kept so the site can be published again."""

    @abstractmethod
    def delete_site(self, site_id: str, hosts: list[str]) -> None:
        """Remove every pointer and every stored file of the site."""

    @abstractmethod
    def get_publish_status(self, site_id: str, host: str) -> dict | None:
        """The live pointer for this hostname if it belongs to this site, else None."""

    @abstractmethod
    def resolve_site_hostname(self, host: str) -> dict | None:
        """host -> {site_id, version, status}, or None."""


# ------------------------------------------------------------------------------------------------------------------ local (development and tests)
class LocalDirectoryProvider(HostingProvider):
    name = "local"

    def __init__(self, root: str | Path, fail_after: int | None = None):
        self.root = Path(root)
        self.fail_after = fail_after  # test hook: raise after this many files have been written

    def _atomic(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def _ptr(self, host: str) -> Path:
        return self.root / "hosts" / f"{host}.json"

    def publish_site(self, site_id, host, files, version):
        base = self.root / "sites" / site_id / f"v{version}"
        written = 0
        for path, data in sorted(files.items()):
            if self.fail_after is not None and written >= self.fail_after:
                raise HostingError("upload_failed", "The hosting provider rejected the upload.", retryable=True)
            self._atomic(base / path, data)
            written += 1
        self._atomic(self._ptr(host), json.dumps(pointer(site_id, version)).encode())  # the switch: only now does the public see the new version
        for v in sorted(int(p.name[1:]) for p in (self.root / "sites" / site_id).glob("v*") if p.name[1:].isdigit())[:-KEEP_VERSIONS]:
            _rmtree(self.root / "sites" / site_id / f"v{v}")
        return PublishResult(version, len(files), sum(len(d) for d in files.values()))

    def set_status(self, site_id, host, version, status):
        self._atomic(self._ptr(host), json.dumps(pointer(site_id, version, status)).encode())

    def unpublish_site(self, site_id, host):
        self._ptr(host).unlink(missing_ok=True)

    def delete_site(self, site_id, hosts):
        for h in hosts:
            self._ptr(h).unlink(missing_ok=True)
        _rmtree(self.root / "sites" / site_id)

    def resolve_site_hostname(self, host):
        p = self._ptr(host)
        return json.loads(p.read_text()) if p.exists() else None

    def get_publish_status(self, site_id, host):
        r = self.resolve_site_hostname(host)
        return r if r and r["site_id"] == site_id else None

    def read(self, host: str, path: str = "index.html") -> bytes | None:
        """What a visitor to `host` would be served for `path` (None = not found). For tests and local preview of published output."""
        r = self.resolve_site_hostname(host)
        if not r or r["status"] != "published":
            return None
        f = self.root / "sites" / r["site_id"] / f"v{r['version']}" / path
        return f.read_bytes() if f.is_file() else None


def _rmtree(p: Path) -> None:
    import shutil

    shutil.rmtree(p, ignore_errors=True)


# ------------------------------------------------------------------------------------------------------------------ Cloudflare (R2 over the S3 API, Workers KV over the REST API)
def sign_v4(method: str, host: str, path: str, query: str, headers: dict[str, str], payload_hash: str, access_key: str, secret: str, region: str, service: str, amz_date: str) -> dict[str, str]:
    """AWS Signature Version 4. Returns the headers to send (the given ones plus x-amz-date, x-amz-content-sha256 and Authorization). Checked against AWS's published test vector and against
    botocore in tests/test_sites_hosting.py."""
    hdrs = {k.lower(): " ".join(str(v).split()) for k, v in headers.items()}
    hdrs["host"], hdrs["x-amz-date"], hdrs["x-amz-content-sha256"] = host, amz_date, payload_hash
    signed = ";".join(sorted(hdrs))
    canonical = "\n".join([method, quote(path, safe="/~"), query, "".join(f"{k}:{hdrs[k]}\n" for k in sorted(hdrs)), signed, payload_hash])
    day = amz_date[:8]
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])

    def h(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    k = h(h(h(h(("AWS4" + secret).encode(), day), region), service), "aws4_request")
    sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
    out = dict(hdrs)
    out["Authorization"] = f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={signed}, Signature={sig}"
    return out


class CloudflareProvider(HostingProvider):
    name = "cloudflare"
    API = "https://api.cloudflare.com/client/v4"

    def __init__(self, *, account_id: str, api_token: str, kv_namespace_id: str, bucket: str, access_key_id: str, secret_access_key: str, zone_id: str = "",
                 client: httpx.Client | None = None, sleep=time.sleep, attempts: int = 3):
        self.account, self.token, self.kv, self.bucket = account_id, api_token, kv_namespace_id, bucket
        self.ak, self.sk, self.zone = access_key_id, secret_access_key, zone_id
        self.r2_host = f"{account_id}.r2.cloudflarestorage.com"
        self.client = client or httpx.Client(timeout=httpx.Timeout(20.0, connect=8.0))
        self.sleep, self.attempts = sleep, attempts

    def configured(self) -> bool:
        return all((self.account, self.token, self.kv, self.bucket, self.ak, self.sk))

    # ---- transport with retry. Only the HTTP status is ever logged or reported: never a URL, header or body.
    def _send(self, what: str, make_request) -> httpx.Response:
        last: Exception | None = None
        for i in range(self.attempts):
            try:
                r = make_request()
                if r.status_code < 500 and r.status_code != 429:
                    return r
                last = HostingError("provider_error", f"{what} failed (HTTP {r.status_code}).", retryable=True)
            except httpx.HTTPError as exc:
                last = HostingError("provider_unreachable", f"{what} failed: the hosting provider could not be reached ({type(exc).__name__}).", retryable=True)
            log.warning("%s attempt %d/%d failed", what, i + 1, self.attempts)
            if i + 1 < self.attempts:
                self.sleep(0.5 * (2 ** i))
        raise last if isinstance(last, HostingError) else HostingError("provider_error", f"{what} failed.", True)

    def _r2(self, method: str, key: str = "", *, body: bytes = b"", query: str = "", content_type: str | None = None) -> httpx.Response:
        path = f"/{self.bucket}" + (f"/{key}" if key else "")
        amz = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        headers = {"content-type": content_type} if content_type else {}
        signed = sign_v4(method, self.r2_host, path, query, headers, hashlib.sha256(body).hexdigest(), self.ak, self.sk, "auto", "s3", amz)
        url = f"https://{self.r2_host}{quote(path, safe='/~')}" + (f"?{query}" if query else "")
        return self._send(f"R2 {method}", lambda: self.client.request(method, url, content=body or None, headers={k: v for k, v in signed.items() if k != "host"}))

    def _kv(self, method: str, key: str, value: str | None = None) -> httpx.Response:
        url = f"{self.API}/accounts/{self.account}/storage/kv/namespaces/{self.kv}/values/{quote(key, safe='')}"
        h = {"Authorization": f"Bearer {self.token}"}
        if value is not None:
            h["Content-Type"] = "text/plain"
        return self._send(f"KV {method}", lambda: self.client.request(method, url, content=value.encode() if value is not None else None, headers=h))

    def _purge(self, host: str) -> None:
        """Best effort: ask Cloudflare to forget the cached copies. The pointer change is what makes a publish or unpublish correct; this only makes it faster."""
        if not self.zone:
            return
        try:
            self.client.post(f"{self.API}/zones/{self.zone}/purge_cache", headers={"Authorization": f"Bearer {self.token}"},
                             json={"files": [f"https://{host}/", f"https://{host}/privacy/", f"https://{host}/sitemap.xml"]})
        except httpx.HTTPError:
            log.warning("cache purge failed for a site (ignored)")

    def _prefix(self, site_id: str, version: int | None = None) -> str:
        return f"sites/{site_id}/" + (f"v{version}/" if version is not None else "")

    def _list(self, prefix: str) -> list[str]:
        keys, token = [], None
        while True:
            q = f"list-type=2&prefix={quote(prefix, safe='')}" + (f"&continuation-token={quote(token, safe='')}" if token else "")
            r = self._r2("GET", query=q)
            if r.status_code != 200:
                raise HostingError("provider_error", f"R2 list failed (HTTP {r.status_code}).", True)
            if len(r.content) > MAX_LIST_XML_BYTES:  # a listing is a few KB; refuse an oversized body before parsing it (a hostile or broken provider cannot make this parser work hard)
                raise HostingError("provider_error", "R2 returned an unexpectedly large listing.", True)
            root = ET.fromstring(r.content)  # nosec B314 - the body comes from Cloudflare R2 over TLS in answer to our own signed request, is size-capped above, and Python's bundled expat limits entity expansion
            ns = {"s": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
            find = (lambda t: root.findall(f"s:{t}", ns)) if ns else (lambda t: root.findall(t))
            keys += [k.text for c in find("Contents") for k in (c.find("s:Key", ns) if ns else c.find("Key"),) if k is not None and k.text]
            nt = find("NextContinuationToken")
            if not nt or not nt[0].text:
                return keys
            token = nt[0].text

    def publish_site(self, site_id, host, files, version):
        total = 0
        for path, data in sorted(files.items()):
            r = self._r2("PUT", self._prefix(site_id, version) + path, body=data, content_type=content_type_for(path))
            if r.status_code not in (200, 201):
                raise HostingError("upload_failed", f"R2 rejected an upload (HTTP {r.status_code}).", retryable=r.status_code >= 500)
            etag = (r.headers.get("etag") or "").strip('"')
            if etag and etag != hashlib.md5(data, usedforsecurity=False).hexdigest():  # an integrity check against R2's own ETag, not a security use
                raise HostingError("upload_corrupt", "R2 stored an upload that does not match what was sent.", retryable=True)
            total += len(data)
        try:
            r = self._kv("PUT", f"host:{host}", json.dumps(pointer(site_id, version)))  # the switch
            ok, why = r.status_code in (200, 201), f"HTTP {r.status_code}"
        except HostingError as exc:  # the provider kept failing even after retries
            ok, why = False, str(exc)
        if not ok:
            raise HostingError("pointer_failed", f"The website could not be switched to the new version ({why}). The previous version is still live.", retryable=True)
        self._purge(host)
        try:  # keep the last KEEP_VERSIONS versions for rollback, remove older ones
            versions = sorted({int(k.split("/")[2][1:]) for k in self._list(self._prefix(site_id)) if k.split("/")[2][1:].isdigit()})
            for v in versions[:-KEEP_VERSIONS]:
                for k in self._list(self._prefix(site_id, v)):
                    self._r2("DELETE", k)
        except HostingError:
            log.warning("old version cleanup failed (ignored)")
        return PublishResult(version, len(files), total)

    def set_status(self, site_id, host, version, status):
        r = self._kv("PUT", f"host:{host}", json.dumps(pointer(site_id, version, status)))
        if r.status_code not in (200, 201):
            raise HostingError("pointer_failed", f"The hostname status could not be changed (HTTP {r.status_code}).", retryable=r.status_code >= 500)
        self._purge(host)

    def unpublish_site(self, site_id, host):
        r = self._kv("DELETE", f"host:{host}")
        if r.status_code not in (200, 204, 404):
            raise HostingError("pointer_failed", f"The website could not be taken offline (HTTP {r.status_code}).", retryable=r.status_code >= 500)
        self._purge(host)

    def delete_site(self, site_id, hosts):
        for h in hosts:
            self.unpublish_site(site_id, h)
        for k in self._list(self._prefix(site_id)):
            r = self._r2("DELETE", k)
            if r.status_code not in (200, 204, 404):
                raise HostingError("delete_failed", f"R2 could not delete a file (HTTP {r.status_code}).", retryable=r.status_code >= 500)

    def resolve_site_hostname(self, host):
        r = self._kv("GET", f"host:{host}")
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise HostingError("provider_error", f"KV read failed (HTTP {r.status_code}).", True)
        try:
            return json.loads(r.text)
        except ValueError:
            return None

    def get_publish_status(self, site_id, host):
        r = self.resolve_site_hostname(host)
        return r if r and r.get("site_id") == site_id else None


# ------------------------------------------------------------------------------------------------------------------ selection
_override: HostingProvider | None = None


def set_provider(p: HostingProvider | None) -> None:
    """Replace the provider (tests)."""
    global _override
    _override = p


def get_hosting_provider() -> HostingProvider:
    if _override is not None:
        return _override
    if settings.sites_provider == "cloudflare":
        return CloudflareProvider(account_id=settings.cloudflare_account_id, api_token=settings.cloudflare_api_token, kv_namespace_id=settings.cloudflare_kv_namespace_id,
                                  bucket=settings.r2_bucket, access_key_id=settings.r2_access_key_id, secret_access_key=settings.r2_secret_access_key, zone_id=settings.cloudflare_zone_id)
    return LocalDirectoryProvider(settings.sites_local_dir)
