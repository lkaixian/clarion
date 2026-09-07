# CLARION edge proxy (P1.9)

Caddy 2.8. The only host-published service: terminates TLS, redirects
HTTP→HTTPS, sets HSTS + CSP + the security-header set for the whole stack,
and routes `/api/*` → `backend:8000`, everything else → `web:8080`.

The FastAPI app and `web/nginx.conf` deliberately **do not** set HSTS/CSP —
the edge is the single source of truth so there is one place to reason
about them.

## Demo (default)

Nothing to configure. `docker compose --env-file .env.docker up -d --build`
brings up `proxy` with `tls internal` — Caddy issues a cert from its own
local CA. The browser will warn until you trust that CA:

```
docker compose exec proxy caddy trust      # on the demo machine
# or export the root: proxy/caddy_data/pki/authorities/local/root.crt
```

Reach the console at `https://localhost/` (or whatever `CLARION_SITE_ADDRESS`
you set).

## Production — the University internal CA

1. Get a server cert for the CLARION FQDN from the University PKI team. You need:
   - `clarion.crt` — leaf **plus** the issuing/intermediate chain, PEM order leaf→root-1
   - `clarion.key` — the matching private key, PEM, **no passphrase**
2. Drop both in `proxy/certs/` (git-ignored). They mount read-only at
   `/etc/caddy/certs/` in the container.
3. In `.env.docker` set:
   ```
   CLARION_SITE_ADDRESS=clarion.example.edu.my
   CLARION_TLS_DIRECTIVE=tls /etc/caddy/certs/clarion.crt /etc/caddy/certs/clarion.key
   ```
4. Ramp HSTS deliberately (the demo default is `max-age=300`):
   ```
   CLARION_HSTS=max-age=31536000; includeSubDomains
   ```
   Only append `; preload` with the University domain-owner sign-off on the exact FQDN
   (never the apex `example.edu.my`) — a preload entry is near-irreversible.
5. If the workstation NFC bridge is in use, add its origin to the CSP:
   ```
   CLARION_CSP_CONNECT_EXTRA=http://localhost:8770 http://127.0.0.1:8770
   ```
   Do **not** copy demo values (`http://localhost:8000`, etc.) into a
   production CSP — behind the proxy the SPA is same-origin.
6. `docker compose --env-file .env.docker up -d`. Verify:
   ```
   curl -sI https://clarion.example.edu.my/ | grep -Ei 'strict-transport|content-security|x-frame'
   ```

## Rotating the cert

Replace the files in `proxy/certs/` and `docker compose restart proxy`.
Caddy reloads the cert without dropping connections.

## Notes

- **No ACME reachout.** The site block always carries an explicit `tls`
  subdirective (`tls internal` by default, or the mounted cert), which stops
  Caddy from ever trying to issue a public certificate. There is no
  `auto_https` override in the Caddyfile — the HTTP→HTTPS redirect is left on
  deliberately (a plain-HTTP `/healthz` route is carved out for the container
  healthcheck so it needs no TLS).
- **TLS floor** is pinned to `tls1.2 tls1.3` in the site's `tls { }` block.
  If a `must-staple` cert is issued and the box is air-gapped, OCSP stapling
  will fail — ask University PKI **not** to set the must-staple flag.
- `caddy_data` holds the internal CA + issued certs; back it up on the demo
  box if you want the trusted CA to survive a `docker compose down -v`.
- **Network split (P1.9):** `web` and the proxy sit on the `edge` network;
  the data/PACS tier (mariadb, minio, redis, orthanc) is on `internal`;
  `backend` bridges both. So a compromised `web`/edge can't reach the
  database, and the data tier can't reach the API.
- The CSP keeps `style-src-attr 'unsafe-inline'` — React renders `style={{}}`
  props to inline `style=` attributes, which genuinely need it.
  `style-src-elem 'self'` still blocks injected `<style>`/`<link>`. Moving
  the inline styles to classes and dropping `'unsafe-inline'` entirely is a
  follow-up.
- HTTP/3 is disabled (`protocols h1 h2`) because only TCP 443 is published.
