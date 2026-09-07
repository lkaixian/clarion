// Runtime API-base config. In a container this file is OVERWRITTEN at start
// by web/entrypoint.sh from the $API_BASE env var (see web/Dockerfile,
// web/nginx.conf). This committed copy is the local-dev / static-preview
// stub: an empty value tells web/src/api/client.js to fall back to
// import.meta.env.VITE_API_BASE, then to http://localhost:8000.
//
// Do not fingerprint or long-cache this file (nginx serves it no-store).
window.__CLARION_API_BASE__ = "";
