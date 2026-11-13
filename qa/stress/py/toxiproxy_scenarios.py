"""Tiny Toxiproxy HTTP-API client (plain httpx) + the toxics the RN1-RN10 tests need.

    with Proxy(BASE_URL) as px:                 # px.url is the proxied BASE_URL
        with px.toxic("latency", latency=800, jitter=300): ...
        with px.toxic("timeout", stream="downstream", timeout=0): ...   # response never arrives
        with px.down(): ...                                             # blackout

Streams: "upstream" = client->server, "downstream" = server->client.
Toxics: latency{latency,jitter} bandwidth{rate KB/s} timeout{timeout ms, 0=stall forever}
        reset_peer{timeout ms} limit_data{bytes}.
Note: through an https BASE_URL the TLS SNI is 127.0.0.1; a proxy with strict_sni_host
(proxy/Caddyfile) refuses it, so point BASE_URL at the plain-http backend for these tests.
"""
import contextlib
import os
from urllib.parse import urlsplit

import httpx

API = os.environ.get("TOXIPROXY_URL", "http://localhost:8474").rstrip("/")
LISTEN_PORT = int(os.environ.get("TOXIPROXY_LISTEN_PORT", "18080"))


def available():
    try:
        return httpx.get(f"{API}/version", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


class Proxy:
    def __init__(self, base_url, name="clarion", listen_port=LISTEN_PORT, upstream_host_override=None):
        u = urlsplit(base_url)
        port = u.port or (443 if u.scheme == "https" else 80)
        host = upstream_host_override or os.environ.get("TOXIPROXY_UPSTREAM_HOST") or u.hostname
        self.name, self.listen = name, f"0.0.0.0:{listen_port}"
        self.upstream = f"{host}:{port}"
        # TOXIPROXY_CLIENT_HOST: name the client uses to reach the proxy (default 127.0.0.1). Needed when the target
        # checks the TLS name / Host header (map the name to 127.0.0.1 in /etc/hosts for the duration of the run).
        chost = os.environ.get("TOXIPROXY_CLIENT_HOST") or "127.0.0.1"
        self.url = f"{u.scheme}://{chost}:{listen_port}{u.path.rstrip('/')}"

    def __enter__(self):
        httpx.delete(f"{API}/proxies/{self.name}", timeout=5)  # leftover from a crashed run
        r = httpx.post(f"{API}/proxies", timeout=5,
                       json={"name": self.name, "listen": self.listen, "upstream": self.upstream, "enabled": True})
        r.raise_for_status()
        return self

    def __exit__(self, *exc):
        httpx.delete(f"{API}/proxies/{self.name}", timeout=5)

    @contextlib.contextmanager
    def toxic(self, type_, stream="downstream", toxicity=1.0, **attributes):
        name = f"{type_}-{stream}"
        httpx.post(f"{API}/proxies/{self.name}/toxics", timeout=5, json={
            "name": name, "type": type_, "stream": stream, "toxicity": toxicity, "attributes": attributes,
        }).raise_for_status()
        try:
            yield
        finally:
            httpx.delete(f"{API}/proxies/{self.name}/toxics/{name}", timeout=5)

    @contextlib.contextmanager
    def down(self):
        """Blackout: connections are refused/dropped while inside the block."""
        httpx.post(f"{API}/proxies/{self.name}", timeout=5, json={"enabled": False}).raise_for_status()
        try:
            yield
        finally:
            httpx.post(f"{API}/proxies/{self.name}", timeout=5, json={"enabled": True}).raise_for_status()
