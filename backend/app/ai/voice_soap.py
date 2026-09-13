"""
Voice -> structured SOAP note (P4.3c, the tender).

Two stages, both fully local -- no cloud call, same the tender
discipline as the rest of ai/:
1. Speech-to-text: `faster-whisper` (CTranslate2, MIT) transcribes the
   clinician's dictation. Degrades to "unavailable" if the package isn't
   installed or the model fails to load -- same discipline as ai/ocr.py's
   Tesseract-availability check. First use downloads the model from
   Hugging Face and caches it locally (a one-time, host-setup step, same
   category as `ollama pull` -- see docs/deployment.md); inference itself
   never leaves the machine.
2. Structuring: the local LLM (ai/local_llm.py) segments the raw
   transcript into SOAP fields, strict JSON, same parse-defensively
   pattern as ai/nric_ocr.py.

Never raises: any failure at either stage degrades rather than 500s, and
never silently drops what the clinician said -- if segmentation fails, the
raw transcript still comes back in the `subjective` field so nothing
dictated is lost, just unstructured.

A duration cap (CLARION_WHISPER_MAX_SECONDS, default 600s) refuses to
transcribe an over-long clip -- the endpoint's byte-size cap alone doesn't
bound CPU time, since a low-bitrate recording packs a long clip into few
bytes (voltagent security review, 2026-09-13).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Optional

from .local_llm import generate_text

logger = logging.getLogger("clarion.voice_soap")

_EMPTY_SOAP = {"subjective": "", "objective": "", "assessment": "", "plan": ""}

# The 15MB upload cap (routers/consultation.py) bounds bytes, not audio
# DURATION -- a low-bitrate clip can pack a very long clip into that. This
# bounds worst-case CPU time in the shared threadpool a hostile/buggy
# client could otherwise tie up with a many-minutes-long "dictation".
# Best-effort: if duration can't be read from the container, transcription
# proceeds anyway (bounded further only by the byte cap) rather than
# rejecting a legitimate short clip whose container lacks duration metadata.
_MAX_AUDIO_SECONDS = int(os.environ.get("CLARION_WHISPER_MAX_SECONDS", "600"))  # 10 minutes


def _duration_seconds(path: str) -> Optional[float]:
    try:
        import av
        with av.open(path) as container:
            return container.duration / 1_000_000 if container.duration else None
    except Exception:
        return None

# Lazy, process-wide singleton -- loading a Whisper model takes seconds;
# doing that per-request would make every dictation pay a multi-second tax.
# _UNSET vs. None distinguishes "not tried yet" from "tried and failed"
# with one variable instead of two.
_UNSET = object()
_model = _UNSET


def _get_model():
    global _model
    if _model is not _UNSET:
        return _model
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        logger.warning("voice_soap: faster-whisper not installed -- voice dictation unavailable.")
        _model = None
        return None
    model_size = os.environ.get("CLARION_WHISPER_MODEL", "small")
    # ponytail: CPU/int8 by default so this runs on any demo laptop with no
    # GPU; CLARION_WHISPER_DEVICE=cuda + float16 for the GPU path.
    device = os.environ.get("CLARION_WHISPER_DEVICE", "cpu")
    compute_type = "float16" if device == "cuda" else "int8"
    try:
        _model = WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception:
        logger.exception("voice_soap: failed to load Whisper model %r (device=%r)", model_size, device)
        _model = None
    return _model


def transcribe(audio_bytes: bytes, suffix: str = ".webm") -> Optional[str]:
    """Raw speech-to-text. None if unavailable/failed -- never raises."""
    model = _get_model()
    if model is None:
        return None
    # faster-whisper wants a file path (it decodes via PyAV/ffmpeg under
    # the hood) -- write to a temp file rather than require an in-memory
    # decode path for whatever compressed format the browser recorded.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        duration = _duration_seconds(tmp_path)
        if duration is not None and duration > _MAX_AUDIO_SECONDS:
            logger.warning(
                "voice_soap: audio duration %.0fs exceeds the %ds cap, refusing to transcribe",
                duration, _MAX_AUDIO_SECONDS,
            )
            return None

        segments, _info = model.transcribe(tmp_path, beam_size=1)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return text or None
    except Exception:
        logger.exception("voice_soap: transcription failed")
        return None
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


_SOAP_PROMPT = (
    "You are a clinical scribe. Segment this dictated transcript from a "
    "clinician into SOAP note fields. Respond with STRICT JSON and nothing "
    "else -- no markdown fences, no commentary:\n"
    '{"subjective": "...", "objective": "...", "assessment": "...", "plan": "..."}\n'
    "Use an empty string for any field not mentioned. Do not invent content "
    "not present in the transcript.\n\nTranscript:\n"
)


def structure_as_soap(transcript: str) -> dict:
    """Best-effort JSON segmentation via the local LLM. Falls back to the
    whole transcript in `subjective` (unstructured but not lost) if the LLM
    is unavailable or returns unparseable JSON."""
    raw = generate_text(_SOAP_PROMPT + transcript, max_tokens=500)
    if raw:
        try:
            if raw.startswith("```"):
                raw = raw.strip("`")
                if raw.lower().startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            data = json.loads(raw)
            return {field: str(data.get(field, "") or "") for field in _EMPTY_SOAP}
        except Exception:
            logger.warning("voice_soap: local-LLM SOAP segmentation unparseable, using raw transcript")
    return {**_EMPTY_SOAP, "subjective": transcript}


def voice_to_soap(audio_bytes: bytes, suffix: str = ".webm") -> dict:
    """Public entry point. Always returns {"transcript": Optional[str],
    "soap": {4 string fields}} -- never raises. `transcript` is None only
    when speech-to-text itself is unavailable/failed; a segmentation
    failure still returns the transcript, just unstructured (see above)."""
    transcript = transcribe(audio_bytes, suffix=suffix)
    if transcript is None:
        return {"transcript": None, "soap": dict(_EMPTY_SOAP)}
    return {"transcript": transcript, "soap": structure_as_soap(transcript)}
