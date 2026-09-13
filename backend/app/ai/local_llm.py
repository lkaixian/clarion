"""
On-prem AI inference engine (P4.3, the tender).

Talks to a local Ollama server (http://localhost:11434 by default) over
plain HTTP on the machine itself -- no third-party network call, ever. This
replaces the old Anthropic-backed paths in summarize.py and nric_ocr.py
(see healthcare/Security Audit.md finding C1, now resolved by this module).

Same "never raise, caller always has a deterministic fallback" discipline
those two callers already used for the old cloud path: every function here
returns None on ANY failure (Ollama not running, model not pulled, timeout,
malformed response) instead of raising, so a demo laptop with no GPU/Ollama
degrades to the existing rule-based/Tesseract paths rather than 500ing.

Config (all optional -- sane defaults for a single demo machine):
  CLARION_LOCAL_LLM_URL       default http://localhost:11434
  CLARION_LOCAL_LLM_MODEL     default "llama3.2"   (text)
  CLARION_LOCAL_VISION_MODEL  default "llava"       (image + text)
  CLARION_LOCAL_LLM_TIMEOUT   default 30 (seconds, total request timeout)
  CLARION_DISABLE_LOCAL_AI    unset/false by default -- set to force every
                               caller straight to its fallback (e.g. a venue
                               laptop with no GPU on stage). Opt-OUT, not
                               opt-in: unlike the old cloud path, nothing
                               here ever leaves the machine, so there is no
                               data-sovereignty reason to default it off.

Deploy note: `ollama pull llama3.2` and `ollama pull llava` (or whichever
models are configured above) must be run once on the target host -- see
docs/deployment.md.

CLARION_LOCAL_LLM_URL is refused (logged, treated as unavailable -- same
never-raise contract) unless it resolves to loopback/private/link-local --
see _is_on_prem_host. Not attacker-reachable input, just a guard against a
copy-paste deploy mistake reintroducing the tender's exact problem.
"""
from __future__ import annotations

import base64
import ipaddress
import logging
import os
import socket
from typing import Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("clarion.local_llm")

_DEFAULT_URL = "http://localhost:11434"
_DEFAULT_TEXT_MODEL = "llama3.2"
_DEFAULT_VISION_MODEL = "llava"
_TRUTHY = {"1", "true", "yes", "on"}


def _base_url() -> str:
    return os.environ.get("CLARION_LOCAL_LLM_URL", _DEFAULT_URL).rstrip("/")


def _is_on_prem_host(url: str) -> bool:
    """Defense-in-depth for the tender: refuse to send anything (PHI,
    MyKad photos) to a host that doesn't resolve to loopback/private/
    link-local, even though CLARION_LOCAL_LLM_URL is operator-set, not
    attacker-reachable, today. Without this, a copy-paste mistake in a
    deploy's .env (pasting a public host/tunnel URL) would silently
    reintroduce the exact cloud-exfiltration Security Audit finding C1 this
    module exists to close, with no error to say so."""
    hostname = urlparse(url).hostname
    if not hostname:
        return False
    try:
        addr = ipaddress.ip_address(socket.gethostbyname(hostname))
    except (socket.gaierror, ValueError):
        return False
    return addr.is_loopback or addr.is_private or addr.is_link_local


def _timeout() -> float:
    try:
        return float(os.environ.get("CLARION_LOCAL_LLM_TIMEOUT", "30"))
    except ValueError:
        return 30.0


def local_llm_enabled() -> bool:
    return os.environ.get("CLARION_DISABLE_LOCAL_AI", "").strip().lower() not in _TRUTHY


def _call_ollama(model: str, prompt: str, *, images: Optional[list[str]], max_tokens: int, temperature: float) -> Optional[str]:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": temperature},
    }
    if images:
        payload["images"] = images
    base_url = _base_url()
    if not _is_on_prem_host(base_url):
        logger.error(
            "local_llm: CLARION_LOCAL_LLM_URL=%r is not loopback/private/link-local -- "
            "refusing to send data off-machine. Check the "
            "deploy's .env for a mistaken cloud/tunnel URL.", base_url,
        )
        return None
    try:
        resp = httpx.post(f"{base_url}/api/generate", json=payload, timeout=_timeout())
        resp.raise_for_status()
        text = resp.json().get("response", "").strip()
        return text or None
    except Exception:
        # Ollama not running, model not pulled, timeout, bad JSON -- any of
        # these degrades to the caller's deterministic/Tesseract fallback
        # rather than breaking the request.
        logger.warning("local_llm: %s generation unavailable, caller falls back", model, exc_info=True)
        return None


def generate_text(prompt: str, *, max_tokens: int = 400) -> Optional[str]:
    """Plain-text completion. None on any failure -- never raises."""
    if not local_llm_enabled():
        return None
    model = os.environ.get("CLARION_LOCAL_LLM_MODEL", _DEFAULT_TEXT_MODEL)
    return _call_ollama(model, prompt, images=None, max_tokens=max_tokens, temperature=0.2)


def generate_vision_text(prompt: str, image_bytes: bytes, *, max_tokens: int = 200) -> Optional[str]:
    """Multimodal completion (image + prompt), raw text back -- caller
    parses/validates it (e.g. as JSON). None on any failure -- never raises.
    temperature=0 since callers use this for extraction, not prose."""
    if not local_llm_enabled():
        return None
    model = os.environ.get("CLARION_LOCAL_VISION_MODEL", _DEFAULT_VISION_MODEL)
    b64_image = base64.b64encode(image_bytes).decode("ascii")
    return _call_ollama(model, prompt, images=[b64_image], max_tokens=max_tokens, temperature=0)
