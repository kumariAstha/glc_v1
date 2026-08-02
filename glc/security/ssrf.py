"""SSRF guards for server-side URL fetches (C1 #14/#75, #92).

The LLM plane fetches caller-supplied image URLs and inlines them as
data: URLs before handing them to a provider. Without a guard, a caller
can point those URLs at internal services (cloud metadata endpoints,
loopback admin ports, RFC1918 hosts) and use the gateway as a confused
deputy. Redirects make an allowlist on the literal URL insufficient — a
public host can 302 to ``http://169.254.169.254/``.

This module resolves the host to concrete IPs, rejects any address that
is private / loopback / link-local / reserved (IPv4 *and* IPv6), and
provides a fetch wrapper that follows redirects manually so every hop is
re-validated.
"""

from __future__ import annotations

import base64
import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

# Follow at most this many redirect hops (each re-validated).
MAX_REDIRECTS = 4
# Cap the fetched body so a huge internal blob can't be amplified.
MAX_IMAGE_BYTES = 12 * 1024 * 1024  # 12 MiB
FETCH_TIMEOUT = 30


def _ip_is_forbidden(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if `ip` must never be reachable from a server-side fetch."""
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return True
    # IPv6 wrappers around forbidden IPv4 space (e.g. ::ffff:169.254.169.254,
    # 6to4 2002::/16). Unwrap and re-check the embedded IPv4.
    if isinstance(ip, ipaddress.IPv6Address):
        if getattr(ip, "is_site_local", False):
            return True
        mapped = ip.ipv4_mapped or ip.sixtofour
        if mapped is not None and _ip_is_forbidden(mapped):
            return True
    return False


def _resolve_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve `host` (name or literal) to every IP it maps to."""
    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    # A bare IP literal must still be validated (never trust getaddrinfo alone).
    try:
        ips.append(ipaddress.ip_address(host))
        return ips
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise HTTPException(400, f"cannot resolve host {host!r}: {e}") from e
    for info in infos:
        sockaddr = info[4]
        raw = sockaddr[0]
        try:
            ips.append(ipaddress.ip_address(raw.split("%")[0]))
        except ValueError:
            continue
    if not ips:
        raise HTTPException(400, f"cannot resolve host {host!r}") from None
    return ips


def assert_safe_url(url: str) -> str:
    """Validate a single URL. Raises HTTPException(400) if unsafe.

    Requires an http(s) scheme and a hostname whose every resolved IP is a
    routable public address. Returns the url on success.
    """
    if not isinstance(url, str):
        raise HTTPException(400, "url must be a string") from None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(400, f"unsupported url scheme {parsed.scheme!r}; only http/https allowed") from None
    host = parsed.hostname
    if not host:
        raise HTTPException(400, "url has no host") from None
    for ip in _resolve_ips(host):
        if _ip_is_forbidden(ip):
            raise HTTPException(400, "url resolves to a disallowed (private/loopback/reserved) address") from None
    return url


async def fetch_bytes(url: str) -> tuple[bytes, str]:
    """Fetch a URL safely: validate every hop, no automatic redirects.

    Returns (content, content_type). Raises HTTPException(400) on any
    validation failure or transport error.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GLCv1/0.1; +image-resolver)",
        "Accept": "image/*,*/*;q=0.8",
    }
    current = url
    async with httpx.AsyncClient(
        timeout=FETCH_TIMEOUT, follow_redirects=False, headers=headers
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            assert_safe_url(current)
            try:
                r = await client.get(current)
            except httpx.HTTPError as e:
                raise HTTPException(400, f"failed to fetch url: {e}") from e
            if r.is_redirect:
                location = r.headers.get("location")
                if not location:
                    raise HTTPException(400, "redirect without location header")
                # Resolve relative redirects against the current URL, then
                # re-validate on the next loop iteration.
                current = str(httpx.URL(current).join(location))
                continue
            try:
                r.raise_for_status()
            except httpx.HTTPError as e:
                raise HTTPException(400, f"failed to fetch url: {e}") from e
            content = r.content
            if len(content) > MAX_IMAGE_BYTES:
                raise HTTPException(400, "fetched resource exceeds size cap")
            ctype = (r.headers.get("content-type") or "image/png").split(";")[0].strip()
            return content, ctype
    raise HTTPException(400, "too many redirects") from None


async def fetch_to_data_url(url: str) -> str:
    """Safe replacement for the old inline fetch: returns a data: URL."""
    content, ctype = await fetch_bytes(url)
    b64 = base64.b64encode(content).decode()
    return f"data:{ctype};base64,{b64}"
