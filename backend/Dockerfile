# CLARION FastAPI backend -- multi-stage production image.
# Build context is ./backend (see docker-compose.yml `build: ./backend`).
#
# Stage 1 (builder): resolve + install Python deps into a self-contained venv.
# Stage 2 (runtime) : slim image, no build toolchain, non-root, venv copied in.
#
# No network access is required at *runtime* -- every dependency (including
# gunicorn, which is not in requirements.txt yet) is baked in at build time.

# ---------------------------------------------------------------------------
# Stage 1 -- builder
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# build-essential/libffi/libssl headers cover the (rare) case where a pinned
# dependency has no manylinux wheel for cp312. Stays out of the runtime image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt ./

# requirements.txt now pins gunicorn + uvicorn-worker (uvicorn 0.52 dropped the
# built-in `uvicorn.workers` module, so the CMD uses `uvicorn_worker.UvicornWorker`).
RUN pip install --no-cache-dir -r requirements.txt

# NRIC OCR (ai/nric_ocr.py): RapidOCR = PaddleOCR models on ONNX Runtime, CPU, models inside the
# wheel. Installed --no-deps so it takes opencv-python-headless (no libGL in the slim image)
# instead of opencv-python; onnxruntime/numpy/Pillow/PyYAML already come from requirements.txt.
RUN pip install --no-cache-dir opencv-python-headless==4.10.0.84 pyclipper==1.3.0.post6 shapely==2.0.7 six tqdm     && pip install --no-cache-dir --no-deps rapidocr-onnxruntime==1.4.4

# ---------------------------------------------------------------------------
# Stage 2 -- runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app

# tesseract-ocr is the native engine behind pytesseract (NRIC OCR path).
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Non-root runtime user.
RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY . /app

# Writable data dirs:
#   /app/data    -> CWD at runtime; SQLite lands here (database.py uses the
#                   relative path "sqlite:///./clarion.db"). Mount a named
#                   volume here. Replaced by MariaDB in roadmap task P1.3.
#   /app/uploads -> UPLOAD_ROOT (Path(__file__).../uploads). Mount a volume.
RUN mkdir -p /app/data /app/uploads \
    && chown -R app:app /app

USER app

# Run from /app/data so "./clarion.db" resolves to /app/data/clarion.db.
# The `app` package stays importable via PYTHONPATH=/app.
WORKDIR /app/data

EXPOSE 8000

# P5.1: /healthz is a pure liveness probe (no dependency checks) -- see
# app/main.py. /readyz (DB + object store) exists too but a container
# healthcheck should answer "is the process alive" not "is it ready for
# traffic", the same distinction Kubernetes draws between the two probes.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

# 4 uvicorn workers matches the On-Prem Architecture pooling math -- see
# database.py's own comment: pool_size=10 + max_overflow=30 per worker =>
# 4 x 40 = 160 conns, under MariaDB's max_connections=200 with headroom for
# clarion_migrate/clarion_report/exporters. (This comment used to say
# max_overflow=10; database.py was tuned to 30 without updating it here --
# found during P5.2 load testing.)
# uvicorn 0.52 removed the built-in `uvicorn.workers` module, so we use the
# standalone `uvicorn-worker` package installed in the builder stage.
#
# forwarded-allow-ips is NOT hardcoded here. gunicorn reads the
# FORWARDED_ALLOW_IPS env var (default 127.0.0.1). The old "*" trusted
# X-Forwarded-* / -Proto from any peer, which let a client spoof its IP and
# defeat every per-IP rate limit (slowapi keys on it) -- worse while the
# backend port is published to the host. Set FORWARDED_ALLOW_IPS to the edge
# proxy's address/subnet in deployment (roadmap P1.9); leave it at the safe
# default otherwise. See docs/deployment.md.
#
# P5.2 load-test tuning (see backend/loadtest/):
# --timeout 60: gunicorn's 30s default risked SIGKILLing a worker mid-request
#   on the local-LLM/whisper paths (CDS hint, voice-to-soap, narrative), which
# run CPU-bound inference with no GPU guarantee. A true
#   fix is making those async/backgrounded; this is the stopgap so a slow
#   inference doesn't also lose the HTTP response.
# --graceful-timeout 30: give an in-flight request time to finish before a
#   worker restart (recycle below, or a deploy) kills it outright.
# --max-requests 2000 --max-requests-jitter 200: recycle each worker after
#   ~2000 requests (jittered so all 4 don't restart together) -- bounds any
#   slow per-request memory growth under sustained load; the jitter is what
#   avoids a synchronized restart-storm dropping all 4 workers at once.
CMD ["gunicorn", "app.main:app", \
     "-k", "uvicorn_worker.UvicornWorker", \
     "-w", "4", \
     "-b", "0.0.0.0:8000", \
     "--timeout", "60", \
     "--graceful-timeout", "30", \
     "--max-requests", "2000", \
     "--max-requests-jitter", "200", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
