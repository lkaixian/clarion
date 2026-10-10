# CLARION web console -- React 19 + Vite, built to static assets and served
# by nginx. Build context is ./web (see docker-compose.yml `build: ./web`).
#
# Stage 1 (build)  : node:20-alpine, `npm ci` + `npm run build` -> /app/dist
# Stage 2 (runtime): nginx:1.27-alpine serving /usr/share/nginx/html
#
# Runtime API base is injected (no rebuild) by entrypoint.sh, which writes
#   window.__CLARION_API_BASE__ = "<$API_BASE>"
# into /usr/share/nginx/html/config.js on container start.

# ---------------------------------------------------------------------------
# Stage 1 -- build
# ---------------------------------------------------------------------------
FROM node:20-alpine AS build

WORKDIR /app

# Install deps first for layer caching (package-lock.json is committed).
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2 -- runtime
# ---------------------------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

# curl is used by the container HEALTHCHECK.
RUN apk add --no-cache curl

# SPA + /api reverse-proxy config.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/snippets/security-headers.conf

# Static build output.
COPY --from=build /app/dist /usr/share/nginx/html

# Runtime config injector. The official nginx image runs every executable in
# /docker-entrypoint.d/ before starting nginx, so no ENTRYPOINT override needed.
COPY entrypoint.sh /docker-entrypoint.d/40-clarion-runtime-config.sh
RUN chmod +x /docker-entrypoint.d/40-clarion-runtime-config.sh

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/ >/dev/null || exit 1

# nginx:alpine's own entrypoint ends with `exec nginx -g 'daemon off;'`.
