"""Safe fetching of URLs that come from outside (scraper results, user input).

Media and subtitle URLs returned by third-party scrapers are untrusted. A plain
urllib.urlopen() would follow them anywhere — file:// paths, or internal addresses such as
the ECS credentials endpoint (169.254.170.2), the VPC, or localhost. safe_urlopen() only
allows http(s) to public internet addresses, and checks every redirect the same way.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse
import urllib.request

# ffmpeg / ffprobe may only read the local file they are given, as a normal audio/video
# container: a crafted media file (e.g. an HLS or concat playlist) could otherwise make them
# open other URLs or local files.
FFMPEG_INPUT_SAFETY = [
    "-protocol_whitelist", "file",
    "-format_whitelist", "mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,avi,flv,mpegts,asf,mp3,wav,ogg,aac,flac",
]


class UnsafeURL(ValueError):
    pass


def check_url(url: str) -> None:
    """Raise UnsafeURL unless `url` is http(s) and its host resolves only to public addresses."""
    parts = urllib.parse.urlsplit(url or "")
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsafeURL(f"only http(s) URLs are fetched, not {parts.scheme or 'none'!r}")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURL(f"cannot resolve {parts.hostname}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise UnsafeURL(f"{parts.hostname} resolves to a non-public address ({ip})")


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_CheckedRedirects)


def safe_urlopen(url: str, headers: dict | None = None, timeout: float = 30):
    """urlopen() for untrusted URLs: public http(s) targets only, redirects re-checked."""
    check_url(url)
    return _opener.open(urllib.request.Request(url, headers=headers or {}), timeout=timeout)
