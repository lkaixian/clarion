"""
Cloud-AI egress guard.

the tender (University HealthCare) requires the embedded intelligent
engine to run "without dependency on third-party AI cloud APIs", for data
sovereignty and offline continuity. The security review also found that with
only ANTHROPIC_API_KEY set, ai/summarize.py posts the full patient record and
ai/nric_ocr.py posts the photographed MyKad image to Anthropic -- the MyKad
path from an unauthenticated endpoint.

Until the on-prem inference engine lands (roadmap P4.3), the cloud call paths
are kept in the tree but are DISABLED BY DEFAULT. They activate only when a
developer explicitly opts in with BOTH:

    ANTHROPIC_API_KEY=<key>
    CLARION_ALLOW_CLOUD_AI=1        # explicit, deliberate dev override

With the override absent, every AI feature falls back to its deterministic /
local path (which is also what runs for the demo). See:
  healthcare/Security Audit.md  (finding C1)
  healthcare/On-Prem Clinical AI.md
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}
_warned = False


def cloud_ai_enabled() -> bool:
    """True only when a developer has deliberately opted in to third-party
    cloud AI calls. Default is False -- callers must use their local /
    deterministic fallback path."""
    global _warned
    if os.environ.get("CLARION_ALLOW_CLOUD_AI", "").strip().lower() not in _TRUTHY:
        return False
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    if not _warned:
        logger.warning(
            "CLARION_ALLOW_CLOUD_AI is set: third-party cloud AI calls are "
            "ENABLED. Patient data may leave the local environment. This must "
            "never be set in a campus/production deployment."
        )
        _warned = True
    return True
