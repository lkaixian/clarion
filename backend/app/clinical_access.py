"""Cross-hospital facility-scoping and clinical-record immutability kernel.

Extracted from routers/patients.py (architecture-review follow-up,
2026-09-13). Six other routers already needed these checks -- Admin,
Ancillary, Appointments, Dental, Emergency, PDPA -- and reaching into a
sibling router's "private" (`_`-prefixed) functions to get them --
several call sites did it as a deferred, in-function import specifically to
dodge a circular import against patients.py -- is exactly the kind of
implicit shared kernel that rots as more modules pile on. This module has no
router owner: it is safe for any router (patients.py included) to import at
module scope, and is the one place new clinical tables register their
facility-relationship column (see _FACILITY_RELATIONSHIP_SOURCES below).
"""

from sqlalchemy import select, union
from sqlalchemy.orm import Session

from . import models
from .routers.reception import _malaysia_today

# ---------------------------------------------------------------------------
# Cross-hospital clinical-record immutability helpers
# ---------------------------------------------------------------------------
# A clinical sub-record (Condition / MedicationStatement / AllergyIntolerance
# / Encounter) may be amended via PATCH ONLY when BOTH hold:
#   1. the acting user's facility == the facility that AUTHORED that row, AND
#   2. the patient is CURRENTLY PRESENT at that facility.
# Otherwise the correction mechanism is to APPEND a new entry (the add_*
# POST endpoints stay open to any facility for any patient). Legacy rows with
# a NULL author facility can never satisfy rule #1 and are therefore
# effectively immutable to everyone via PATCH -- the intended safe default.


def _row_author_facility(row) -> "str | None":
    """The facility that authored a clinical sub-record, whichever column
    holds it for that resource type: Condition/AllergyIntolerance ->
    `authored_by_facility`; MedicationStatement -> `recorded_by_facility`
    (NOT `prescribed_by_facility`, which is the -- often external --
    prescriber); Encounter -> `facility_name`."""
    if isinstance(row, models.MedicationStatement):
        return row.recorded_by_facility
    if isinstance(row, models.Encounter):
        return row.facility_name
    # Condition / AllergyIntolerance
    return getattr(row, "authored_by_facility", None)


def _patient_present_at(db: Session, patient_id: str, facility: str) -> bool:
    """True iff the patient is CURRENTLY at `facility` -- either an active
    (undischarged) Admission there, or a same-day (Malaysia-local) queue
    ticket in a still-open state ('waiting' / 'called'). This is rule #2 of
    the cross-facility PATCH guard."""
    if not facility:
        return False

    active_admission = (
        db.query(models.Admission.id)
        .filter(
            models.Admission.patient_id == patient_id,
            models.Admission.facility_name == facility,
            models.Admission.discharged_at.is_(None),
        )
        .first()
    )
    if active_admission is not None:
        return True

    # Reuse reception's single source of truth for "today" in Malaysia-local
    # terms (Asia/Kuala_Lumpur, UTC+8, no DST) -- see models.QueueTicket's
    # docstring for why the queue day is deliberately not the UTC date.
    _utc_start, queue_date = _malaysia_today()
    open_ticket = (
        db.query(models.QueueTicket.id)
        .filter(
            models.QueueTicket.patient_id == patient_id,
            models.QueueTicket.facility_name == facility,
            models.QueueTicket.status.in_(("waiting", "called")),
            models.QueueTicket.queue_date == queue_date,
        )
        .first()
    )
    return open_ticket is not None


def _record_editable(
    db: Session, patient_id: str, row, current_user,
    present_at_caller_facility: "bool | None" = None,
) -> bool:
    """Rule #1 AND rule #2 combined, for the `editable` flag exposed on every
    serialized clinical sub-record. False whenever there is no user context
    (e.g. the unauthenticated emergency scan) or the acting user has no
    facility assigned.

    `present_at_caller_facility` lets a bulk caller (`_serialize_patient`)
    pass in the rule-#2 result it has already computed once for this
    (patient, caller-facility) pair, instead of this function re-running the
    two `_patient_present_at` queries for every clinical sub-record on the
    patient. When None it is computed here as before (the single-row PATCH
    return serializers)."""
    if current_user is None or not getattr(current_user, "facility", None):
        return False
    owner = _row_author_facility(row)
    if not owner or owner != current_user.facility:
        return False
    if present_at_caller_facility is not None:
        return present_at_caller_facility
    return _patient_present_at(db, patient_id, current_user.facility)


def _hidden_author_facilities(db: Session, caller_facility: "str | None") -> set:
    """Facilities whose authored clinical sub-records must be HIDDEN from
    this caller because that facility has set HospitalSetting.records_shared_publicly
    to False. A facility never hides records from its own staff, so
    `caller_facility` is always excluded from the result. Computed once per
    _serialize_patient call."""
    rows = (
        db.query(models.HospitalSetting.facility_name)
        .filter(models.HospitalSetting.records_shared_publicly.is_(False))
        .all()
    )
    return {f for (f,) in rows if f and f != caller_facility}


# ---------------------------------------------------------------------------
# Facility <-> patient relationship (which facilities have ever treated /
# billed / seen this patient) -- drives list_patients' default scope and the
# cross-facility audit flag on get_patient_full_record.
# ---------------------------------------------------------------------------
# Register a new clinical module's table here (its column that names the
# facility) so it participates in both queries below. Every P3 module so far
# (Ancillary/ServiceRequest, Dental/DentalChartEntry, Billing/Bill) has had
# to add itself here -- this is the one place that needs to happen.
_FACILITY_RELATIONSHIP_SOURCES = (
    (models.Encounter, models.Encounter.facility_name),
    (models.Condition, models.Condition.authored_by_facility),
    (models.MedicationStatement, models.MedicationStatement.recorded_by_facility),
    (models.AllergyIntolerance, models.AllergyIntolerance.authored_by_facility),
    (models.Admission, models.Admission.facility_name),
    (models.QueueTicket, models.QueueTicket.facility_name),
    (models.Appointment, models.Appointment.facility_name),
    (models.ServiceRequest, models.ServiceRequest.ordering_facility_name),
    (models.DentalChartEntry, models.DentalChartEntry.facility_name),
    (models.Bill, models.Bill.facility_name),
)


def _facility_known_patient_ids_select(facility: str):
    """Bulk form: a `SELECT patient_id ...` UNION over every
    _FACILITY_RELATIONSHIP_SOURCES table for `facility`, returned as a
    subquery-able selectable (NOT executed here).

    list_patients composes this straight into `Patient.id.in_(...)` so the
    whole default scope -- filter, ORDER BY, LIMIT/OFFSET -- runs in one
    database round-trip. Previously this ran 7 separate `SELECT DISTINCT`
    queries, unioned them into a Python set, then passed the entire set back
    as a literal `IN (...)` list (thousands of bind params at a large
    facility, and the DISTINCT scans happened in full regardless of the
    page requested). Code-review follow-up 2026-09-07 -- backed by the new
    facility-column indexes in migration d5e8a1c4b6f2."""
    return union(
        *(
            select(model.patient_id).where(facility_col == facility)
            for model, facility_col in _FACILITY_RELATIONSHIP_SOURCES
        )
    ).subquery()


def _patient_known_to_facility(db: Session, patient_id: str, facility: str) -> bool:
    """Single-patient form: cheap existence check (short-circuits on the
    first match) for get_patient_full_record's cross-facility audit flag --
    deliberately NOT built from _facility_known_patient_ids_select and a
    membership test, which would scan the facility's ENTIRE patient set just
    to answer one yes/no question on every detail view."""
    for model, facility_col in _FACILITY_RELATIONSHIP_SOURCES:
        hit = (
            db.query(model.patient_id)
            .filter(model.patient_id == patient_id, facility_col == facility)
            .first()
        )
        if hit is not None:
            return True
    return False
