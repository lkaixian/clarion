"""P3.6: Reporting engine (canned operational reports +
 Custom Report Builder -- "select fields from all modules;
filter/sort/group").

Deliberately NOT a generic SQL query builder. A truly generic "pick any
column, filter on any column" builder means a client-supplied field name
reaching a live query -- the #1 injection/authorization-bypass risk for this
kind of feature. Instead: a small, curated registry of facility-local
DATASETS, each declaring its own typed, named `Field`s with an explicit
getter. The "field picker across modules" the clause asks for is generic
OVER this registry (GET /reports/datasets hands the frontend the field
catalogue to render a picker from), never over raw column names.

Facility-local only -- same Design Decision as billing.py (see its module
docstring): no cross-facility aggregation. Every dataset's `query()` filters
on the caller's own `current_user.facility`.

Row cap (_MAX_ROWS): filter/group/sort all run in Python over the fetched
rows, not in SQL. ponytail: fine at clinic scale (thousands of rows per
dataset); if a facility's history grows past the cap, this needs real
SQL-side pagination -- not before.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from . import models

_MAX_ROWS = 5000


# ---------------------------------------------------------------------------
# Field / Dataset registry
# ---------------------------------------------------------------------------

@dataclass
class Field:
    label: str
    type: str  # "string" | "number" | "date" | "bool" | "enum"
    getter: Callable[[Any], Any]
    groupable: bool = False
    filterable: bool = False
    options: Optional[List[str]] = None  # only for type == "enum"

    def spec(self) -> dict:
        d = {"label": self.label, "type": self.type, "groupable": self.groupable, "filterable": self.filterable}
        if self.options is not None:
            d["options"] = self.options
        return d


@dataclass
class Dataset:
    label: str
    query: Callable[[Session, str], Any]  # -> a facility-filtered SQLAlchemy Query
    fields: Dict[str, Field]
    default_fields: List[str] = dc_field(default_factory=list)


def _minutes_between(start_attr: str, end_attr: str) -> Callable[[Any], Optional[float]]:
    def getter(row):
        start, end = getattr(row, start_attr, None), getattr(row, end_attr, None)
        if not start or not end:
            return None
        return round((end - start).total_seconds() / 60.0, 1)
    return getter


def _encounters_query(db: Session, facility: str):
    return (
        db.query(models.Encounter)
        .filter(models.Encounter.facility_name == facility)
        .order_by(models.Encounter.started_at.desc())
        .limit(_MAX_ROWS)
    )


def _admissions_query(db: Session, facility: str):
    return (
        db.query(models.Admission)
        .filter(models.Admission.facility_name == facility)
        .order_by(models.Admission.admitted_at.desc())
        .limit(_MAX_ROWS)
    )


def _ancillary_query(db: Session, facility: str):
    # Facility-local by ORDERING facility -- same scoping signal
    # routers/billing.py uses for a ServiceRequest-derived row.
    return (
        db.query(models.ServiceRequest)
        .filter(models.ServiceRequest.ordering_facility_name == facility)
        .order_by(models.ServiceRequest.created_at.desc())
        .limit(_MAX_ROWS)
    )


def _conditions_query(db: Session, facility: str):
    return (
        db.query(models.Condition)
        .filter(models.Condition.authored_by_facility == facility)
        .order_by(models.Condition.id.desc())
        .limit(_MAX_ROWS)
    )


def _bills_query(db: Session, facility: str):
    return (
        db.query(models.Bill)
        .filter(models.Bill.facility_name == facility)
        .order_by(models.Bill.created_at.desc())
        .limit(_MAX_ROWS)
    )


def _bill_total_cents(b: models.Bill) -> int:
    return sum(i.amount_cents for i in b.items if not i.voided_at)


def _bill_paid_cents(b: models.Bill) -> int:
    return sum(p.amount_cents for p in b.payments if not p.voided_at)


def _admission_los_minutes(a: models.Admission) -> Optional[float]:
    if not a.discharged_at:
        return None
    return round((a.discharged_at - a.admitted_at).total_seconds() / 60.0, 1)


def _lookup_cache(db: Session, model, id_attr: str, name_attr: str) -> Callable[[Any], Optional[str]]:
    """Per-request memoized `row.<id_attr> -> related.<name_attr>` lookup --
    avoids one query per row for a field every report in this registry
    selects (patient name, ward name, catalog item name)."""
    cache: Dict[Optional[str], Optional[str]] = {}

    def getter(row) -> Optional[str]:
        fk = getattr(row, id_attr)
        if fk not in cache:
            obj = db.query(model).filter(model.id == fk).first() if fk else None
            cache[fk] = getattr(obj, name_attr) if obj else None
        return cache[fk]

    return getter


def build_datasets(db: Session) -> Dict[str, Dataset]:
    """Datasets keyed by getters that need a per-request lookup cache (ward
    name, patient name) are built fresh per request rather than module-level
    globals -- the cache must not leak across requests/sessions."""
    patient_name = _lookup_cache(db, models.Patient, "patient_id", "full_name")
    patient_nric = _lookup_cache(db, models.Patient, "patient_id", "national_id")
    catalog_item_name = _lookup_cache(db, models.ServiceCatalogItem, "catalog_item_id", "name")
    ward_name = _lookup_cache(db, models.Ward, "ward_id", "ward_name")

    return {
        "encounters": Dataset(
            label="Encounters (visit summary)",
            query=_encounters_query,
            default_fields=["patient_name", "encounter_type", "started_at", "signed_by_name"],
            fields={
                "patient_name": Field("Patient", "string", patient_name, filterable=True),
                "patient_nric": Field("NRIC / ID", "string", patient_nric, filterable=True),
                "encounter_type": Field(
                    "Encounter type", "enum", lambda r: r.encounter_type,
                    groupable=True, filterable=True,
                    options=["outpatient", "inpatient", "emergency", "transfer"],
                ),
                "reason": Field("Reason", "string", lambda r: r.reason),
                "started_at": Field("Started at", "date", lambda r: r.started_at, filterable=True),
                "signed_by_name": Field("Signed by", "string", lambda r: r.signed_by_name, groupable=True, filterable=True),
                "signed_by_role": Field("Signer role", "string", lambda r: r.signed_by_role, groupable=True),
            },
        ),
        "admissions": Dataset(
            label="Admissions (admission / discharge)",
            query=_admissions_query,
            default_fields=["patient_name", "ward_name", "admitted_at", "discharged_at", "status"],
            fields={
                "patient_name": Field("Patient", "string", patient_name, filterable=True),
                "ward_name": Field("Ward", "string", ward_name, groupable=True, filterable=True),
                "bed_number": Field("Bed", "number", lambda r: r.bed_number),
                "admitted_at": Field("Admitted at", "date", lambda r: r.admitted_at, filterable=True),
                "discharged_at": Field("Discharged at", "date", lambda r: r.discharged_at, filterable=True),
                "status": Field(
                    "Status", "enum", lambda r: "discharged" if r.discharged_at else "active",
                    groupable=True, filterable=True, options=["active", "discharged"],
                ),
                "length_of_stay_minutes": Field("Length of stay (min)", "number", _admission_los_minutes),
            },
        ),
        "ancillary_results": Dataset(
            label="Ancillary requests (lab / imaging / procedure / physio TAT)",
            query=_ancillary_query,
            default_fields=["module", "catalog_item_name", "patient_name", "status", "tat_minutes"],
            fields={
                "module": Field(
                    "Module", "enum", lambda r: r.module, groupable=True, filterable=True,
                    options=list(models.ANCILLARY_MODULES),
                ),
                "catalog_item_name": Field("Item", "string", catalog_item_name, groupable=True, filterable=True),
                "patient_name": Field("Patient", "string", patient_name, filterable=True),
                "status": Field(
                    "Status", "enum", lambda r: r.status, groupable=True, filterable=True,
                    options=["ordered", "signed_off", "cancelled"],
                ),
                "priority": Field("Priority", "enum", lambda r: r.priority, groupable=True, filterable=True, options=["routine", "urgent"]),
                "created_at": Field("Requested at", "date", lambda r: r.created_at, filterable=True),
                "tat_minutes": Field(
                    "Turnaround (min)", "number",
                    _minutes_between("created_at", "_performed_at"),
                    filterable=True,
                ),
                "flag_abnormal": Field("Abnormal", "bool", lambda r: bool(r.result and r.result.flag_abnormal), filterable=True),
                "signed_by_name": Field("Signed by", "string", lambda r: r.result.signed_by_name if r.result else None, groupable=True, filterable=True),
            },
        ),
        "conditions": Dataset(
            label="Conditions (disease-specific)",
            query=_conditions_query,
            default_fields=["patient_name", "name", "status", "is_chronic"],
            fields={
                "patient_name": Field("Patient", "string", patient_name, filterable=True),
                "patient_nric": Field("NRIC / ID", "string", patient_nric, filterable=True),
                "name": Field("Diagnosis", "string", lambda r: r.name, groupable=True, filterable=True),
                "status": Field("Status", "enum", lambda r: r.status, groupable=True, filterable=True, options=["active", "resolved"]),
                "is_chronic": Field("Chronic", "bool", lambda r: bool(r.is_chronic), filterable=True),
                "critical_for_emergency": Field("Emergency-critical", "bool", lambda r: bool(r.critical_for_emergency), filterable=True),
                "diagnosed_at": Field("Diagnosed at", "string", lambda r: r.diagnosed_at, filterable=True),
            },
        ),
        # Closes the forward reference in schemas.BillingStatsOut's
        # docstring ("the full 'Financial performance reports' clause
        # is P3.6's job"). Bill-level only -- a per-category
        # ("total charges by department") breakdown would need a second
        # bill_items dataset; add one if that granularity is actually asked
        # for, not speculatively here.
        "bills": Dataset(
            label="Bills (financial performance)",
            query=_bills_query,
            default_fields=["patient_name", "status", "created_at", "total_amount_cents", "paid_amount_cents"],
            fields={
                "patient_name": Field("Patient", "string", lambda r: r.patient.full_name if r.patient else None, filterable=True),
                "status": Field("Status", "enum", lambda r: r.status, groupable=True, filterable=True, options=["open", "finalized", "voided"]),
                "created_at": Field("Created at", "date", lambda r: r.created_at, filterable=True),
                "finalized_at": Field("Finalized at", "date", lambda r: r.finalized_at, filterable=True),
                "created_by_name": Field("Created by", "string", lambda r: r.created_by_name, groupable=True, filterable=True),
                "total_amount_cents": Field("Total (cents)", "number", _bill_total_cents, filterable=True),
                "paid_amount_cents": Field("Paid (cents)", "number", _bill_paid_cents, filterable=True),
                "outstanding_cents": Field("Outstanding (cents)", "number", lambda r: _bill_total_cents(r) - _bill_paid_cents(r), filterable=True),
                "claim_count": Field("Claims", "number", lambda r: len(r.claims)),
            },
        ),
    }


# `tat_minutes` needs the joined ServiceResult.performed_at, not a plain
# column -- give ServiceRequest rows a transient `_performed_at` attribute
# via the query result rather than a second N+1 lookup per row.
def _attach_performed_at(rows: List[models.ServiceRequest]) -> None:
    for r in rows:
        r._performed_at = r.result.performed_at if r.result else None


# ---------------------------------------------------------------------------
# Filter / group / sort
# ---------------------------------------------------------------------------

class ReportError(ValueError):
    """A client-supplied dataset/field/filter/group-by name was invalid --
    the router turns this into a 422."""


def _validate_fields(dataset: Dataset, keys: List[str], *, groupable_only: bool = False, filterable_only: bool = False) -> None:
    for k in keys:
        f = dataset.fields.get(k)
        if f is None:
            raise ReportError(f"Unknown field: {k}")
        if groupable_only and not f.groupable:
            raise ReportError(f"Field not groupable: {k}")
        if filterable_only and not f.filterable:
            raise ReportError(f"Field not filterable: {k}")


def _matches_filter(f: Field, value: Any, spec: Any) -> bool:
    if f.type == "date":
        if value is None:
            return False
        v = value.date() if isinstance(value, datetime) else value
        lo, hi = (spec or {}).get("from"), (spec or {}).get("to")
        if lo and v < date.fromisoformat(lo):
            return False
        if hi and v > date.fromisoformat(hi):
            return False
        return True
    if f.type == "enum":
        allowed = spec if isinstance(spec, list) else [spec]
        return value in allowed
    if f.type == "bool":
        return bool(value) == bool(spec)
    if f.type == "number":
        if value is None:
            return False
        lo, hi = (spec or {}).get("min"), (spec or {}).get("max")
        if lo is not None and value < lo:
            return False
        if hi is not None and value > hi:
            return False
        return True
    # "string": case-insensitive substring
    return bool(spec) and str(spec).lower() in str(value or "").lower()


def run_report(
    db: Session,
    facility: str,
    dataset_key: str,
    fields: List[str],
    filters: Optional[Dict[str, Any]] = None,
    group_by: Optional[List[str]] = None,
    sort: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    datasets = build_datasets(db)
    dataset = datasets.get(dataset_key)
    if dataset is None:
        raise ReportError(f"Unknown dataset: {dataset_key}")

    fields = fields or list(dataset.default_fields)
    filters = filters or {}
    group_by = group_by or []
    _validate_fields(dataset, fields)
    _validate_fields(dataset, list(filters.keys()), filterable_only=True)
    _validate_fields(dataset, group_by, groupable_only=True)

    rows = dataset.query(db, facility).all()
    if dataset_key == "ancillary_results":
        _attach_performed_at(rows)

    for k, spec in filters.items():
        f = dataset.fields[k]
        rows = [r for r in rows if _matches_filter(f, f.getter(r), spec)]

    if group_by:
        numeric_fields = [k for k in fields if k not in group_by and dataset.fields[k].type == "number"]
        groups: Dict[tuple, dict] = {}
        order: List[tuple] = []
        for r in rows:
            key = tuple(dataset.fields[g].getter(r) for g in group_by)
            if key not in groups:
                groups[key] = {"count": 0, "_sums": {n: 0.0 for n in numeric_fields}, "_n": {n: 0 for n in numeric_fields}}
                order.append(key)
            g = groups[key]
            g["count"] += 1
            for n in numeric_fields:
                v = dataset.fields[n].getter(r)
                if v is not None:
                    g["_sums"][n] += v
                    g["_n"][n] += 1

        columns = [{"key": g, "label": dataset.fields[g].label, "type": dataset.fields[g].type} for g in group_by]
        columns.append({"key": "count", "label": "Count", "type": "number"})
        for n in numeric_fields:
            columns.append({"key": f"avg_{n}", "label": f"Avg {dataset.fields[n].label}", "type": "number"})

        out_rows = []
        for key in order:
            g = groups[key]
            row_vals = list(key) + [g["count"]]
            for n in numeric_fields:
                cnt = g["_n"][n]
                row_vals.append(round(g["_sums"][n] / cnt, 1) if cnt else None)
            out_rows.append([_jsonsafe(v) for v in row_vals])
    else:
        columns = [{"key": k, "label": dataset.fields[k].label, "type": dataset.fields[k].type} for k in fields]
        out_rows = [[_jsonsafe(dataset.fields[k].getter(r)) for k in fields] for r in rows]

    # Sort applies uniformly to either shape -- an unrecognised sort field
    # (e.g. one that only exists pre-grouping) is silently ignored rather
    # than a 422: sort is cosmetic, unlike a field/filter/group-by mistake
    # that would silently change what data is even computed.
    if sort and sort.get("field") in [c["key"] for c in columns]:
        idx = [c["key"] for c in columns].index(sort["field"])
        reverse = sort.get("dir") == "desc"
        out_rows.sort(key=lambda row: (row[idx] is None, row[idx]), reverse=reverse)

    return {"dataset": dataset_key, "columns": columns, "rows": out_rows, "row_count": len(out_rows), "truncated": len(rows) >= _MAX_ROWS}


def _jsonsafe(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def dataset_specs(db: Session) -> List[dict]:
    """GET /reports/datasets payload -- the field-picker catalogue."""
    out = []
    for key, ds in build_datasets(db).items():
        out.append({
            "key": key,
            "label": ds.label,
            "default_fields": ds.default_fields,
            "fields": {k: f.spec() for k, f in ds.fields.items()},
        })
    return out
