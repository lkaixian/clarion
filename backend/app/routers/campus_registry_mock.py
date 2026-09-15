"""MOCK stand-in for the University's real SMP / SMS / e-klinik panel / Registrar
systems. See
`app/campus_registry.py`'s module docstring for why this exists as a mock
rather than a real integration, and `healthcare/Implementation
Roadmap.md`'s P4.8 changelog for the original scoping decision.

Every seeded identity below is entirely FICTIONAL -- not derived from, or
resembling, any real campus student/staff record -- and every response
carries `"mock": true` so nothing here can be mistaken for a real result,
in the UI or in a log line. This router exists to make the integration
POINT real and demoable (a genuine HTTP call, a genuine adapter boundary,
a genuine UI flow) while staying honest that the DATA behind it is a
placeholder.

Deliberately unauthenticated: a real SMP/SMS/e-klinik-panel endpoint would
sit behind the University's own auth, not CLARION's `require_page_access` -- gating
this mock with the latter would demo a shape the real integration won't
have. No PHI/real-data exposure risk either way (every record here is
fictional).
"""
from fastapi import APIRouter, HTTPException

from ..nric import normalize_nric

router = APIRouter(prefix="/mock-campus-registry", tags=["mock-campus-registry (demo stand-in)"])

_MOCK_REGISTRY = {
    normalize_nric("000101-01-0001"): {
        "eligible": True,
        "source": "SMP",
        "full_name": "Ahmad bin Ismail (mock)",
        "id_number": "AI210001",
        "category": "student",
        "faculty_or_department": "Faculty of Computer Science and Information Technology",
        "status": "active",
    },
    normalize_nric("990202-02-0002"): {
        "eligible": True,
        "source": "SMS",
        "full_name": "Nurul Huda binti Zainal (mock)",
        "id_number": "S12345",
        "category": "staff",
        "faculty_or_department": "Registrar's Office",
        "status": "active",
    },
    normalize_nric("951010-05-0003"): {
        "eligible": False,
        "source": "SMP",
        "full_name": "Chong Wei Ling (mock)",
        "id_number": "AI190045",
        "category": "student",
        "faculty_or_department": "Faculty of Civil Engineering and Built Environment",
        "status": "graduated",
    },
    normalize_nric("880808-08-0004"): {
        "eligible": True,
        "source": "e-klinik",
        "full_name": "Lee Chee Keong (mock)",
        "id_number": "STF4488",
        "category": "staff",
        "faculty_or_department": "Faculty of Mechanical and Manufacturing Engineering",
        "status": "active",
    },
}


@router.get("/eligibility/{nric}")
def mock_eligibility(nric: str):
    """Stands in for a real call to the Registrar's system / SMP / SMS /
    e-klinik panel. Any NRIC not in `_MOCK_REGISTRY` 404s, same as a real
    "not found" from an external directory would."""
    record = _MOCK_REGISTRY.get(normalize_nric(nric))
    if record is None:
        raise HTTPException(status_code=404, detail="Not found in mock campus registry")
    return {**record, "mock": True}
