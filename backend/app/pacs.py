"""
PACS integration (P4.7, the tender): a thin client for the
on-prem Orthanc DICOM server (docker-compose.yml's `orthanc` service --
`internal` network only, never host-exposed, see that file's comment).

Same on-prem-only discipline as ai/local_llm.py: CLARION_ORTHANC_URL is
refused unless it resolves to loopback/private/link-local, so a copy-paste
deploy mistake (pasting a public/tunnel URL) can't send patient imaging off
the machine. `_is_on_prem_host` is duplicated from local_llm.py rather than
imported -- the two guards are conceptually unrelated (this module has no
other reason to depend on the `ai` package) and happen to share five lines.

Orthanc is reachable ONLY from the backend container on the internal docker
network, never from a browser directly -- every read a browser makes goes
through routers/pacs.py's own RBAC + facility-scoped proxy, never straight
to Orthanc; that router also checks a requested instance id against the
DicomStudy row's own stored instance-id list before ever calling
`get_instance_file` here, so a guessed/adjacent Orthanc id can't be used to
walk out of the study the caller was actually granted. Orthanc's own HTTP
basic auth (CLARION_ORTHANC_USER/PASSWORD, matching docker-compose.yml's
ORTHANC__REGISTERED_USERS) is defense-in-depth on top of that network
boundary, not a substitute for it.

DICOMweb (WADO-RS) is deliberately NOT used here even though Orthanc has the
plugin enabled -- the viewer loads plain DICOM Part10 files instead (GET
.../file below), which is dwv's simpler, equally standard loading mode and
avoids building a second authenticated reverse-proxy for an open-ended
DICOMweb URL path (a real path-traversal/open-proxy surface for no benefit
at this scale).
"""
from __future__ import annotations

import ipaddress
import logging
import os
import socket
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("clarion.pacs")

_DEFAULT_URL = "http://orthanc:8042"


def _base_url() -> str:
    return os.environ.get("CLARION_ORTHANC_URL", _DEFAULT_URL).rstrip("/")


def _is_on_prem_host(url: str) -> bool:
    hostname = urlparse(url).hostname
    if not hostname:
        return False
    try:
        addr = ipaddress.ip_address(socket.gethostbyname(hostname))
    except (socket.gaierror, ValueError):
        return False
    return addr.is_loopback or addr.is_private or addr.is_link_local


class PacsError(Exception):
    """Orthanc unreachable, refused (not on-prem), or returned an error --
    every router call site turns this into a 503."""


def _timeout() -> float:
    try:
        return float(os.environ.get("CLARION_ORTHANC_TIMEOUT", "30"))
    except ValueError:
        return 30.0


def _auth() -> tuple[str, str] | None:
    user = os.environ.get("CLARION_ORTHANC_USER")
    password = os.environ.get("CLARION_ORTHANC_PASSWORD")
    if not user or not password:
        return None
    return (user, password)


def _client() -> httpx.Client:
    base_url = _base_url()
    if not _is_on_prem_host(base_url):
        logger.error(
            "pacs: CLARION_ORTHANC_URL=%r is not loopback/private/link-local -- "
            "refusing to talk to it. Check the deploy's "
            ".env for a mistaken cloud/tunnel URL.", base_url,
        )
        raise PacsError("Orthanc host is not on-prem")
    return httpx.Client(base_url=base_url, timeout=_timeout(), auth=_auth())


def upload_instance(raw: bytes) -> dict:
    """POST one DICOM Part10 file to Orthanc's REST API (`/instances`).
    Returns Orthanc's own JSON: {"ID": <instance id>, "ParentStudy": <study
    id>, "Status": "Success"|"AlreadyStored", ...}. Raises PacsError on any
    failure -- including a non-DICOM upload, which Orthanc itself rejects."""
    try:
        with _client() as c:
            resp = c.post("/instances", content=raw, headers={"Content-Type": "application/dicom"})
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as e:
        raise PacsError(str(e)) from e


def get_study(orthanc_study_id: str) -> dict:
    """MainDicomTags etc. for one Orthanc study id."""
    try:
        with _client() as c:
            resp = c.get(f"/studies/{orthanc_study_id}")
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as e:
        raise PacsError(str(e)) from e


def get_instance_file(orthanc_instance_id: str) -> bytes:
    """Raw DICOM Part10 bytes for one Orthanc instance id -- the router
    verifies `orthanc_instance_id` is a member of the caller's DicomStudy
    row BEFORE calling this; this function trusts its caller."""
    try:
        with _client() as c:
            resp = c.get(f"/instances/{orthanc_instance_id}/file")
            resp.raise_for_status()
            return resp.content
    except httpx.HTTPError as e:
        raise PacsError(str(e)) from e
