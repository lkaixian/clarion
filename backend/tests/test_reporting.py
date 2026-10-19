"""P3.6 reporting engine (app/reporting_engine.py) + HTTP surface
(routers/reporting.py): dataset field-picker shape, facility scoping,
filter/group-by validation, group-by aggregation, PDF/Excel export, saved-
template visibility/sharing/delete-permission, and the page-gate RBAC layer
(main.py's require_page_access("reporting")).
"""
from datetime import datetime, timedelta, timezone

from app import models
from conftest import _facility, _make_patient


def _service_request(db_session, patient_id, facility, module="laboratory", **overrides):
    item = models.ServiceCatalogItem(module=module, name=overrides.pop("item_name", "Test Item"), unit_price_cents=1000)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    req = models.ServiceRequest(
        patient_id=patient_id, module=module, catalog_item_id=item.id, source="frontdesk",
        status=overrides.pop("status", "ordered"), ordering_facility_name=facility,
        created_at=overrides.pop("created_at", datetime.now(timezone.utc)),
        **overrides,
    )
    db_session.add(req)
    db_session.commit()
    db_session.refresh(req)
    return req


def _service_result(db_session, req, performed_at, flag_abnormal=False):
    res = models.ServiceResult(
        service_request_id=req.id, patient_id=req.patient_id, performed_at=performed_at,
        flag_abnormal=flag_abnormal, signed_by_name="Dr Test", facility_name=req.ordering_facility_name,
    )
    db_session.add(res)
    req.status = "signed_off"
    db_session.commit()
    return res


def _condition(db_session, patient_id, facility, name="Dengue Fever", **overrides):
    cond = models.Condition(patient_id=patient_id, name=name, authored_by_facility=facility, **overrides)
    db_session.add(cond)
    db_session.commit()
    db_session.refresh(cond)
    return cond


def _encounter(db_session, patient_id, facility, **overrides):
    enc = models.Encounter(
        patient_id=patient_id, facility_name=facility,
        encounter_type=overrides.pop("encounter_type", "outpatient"),
        started_at=overrides.pop("started_at", datetime.now(timezone.utc)),
        **overrides,
    )
    db_session.add(enc)
    db_session.commit()
    db_session.refresh(enc)
    return enc


# ---------------------------------------------------------------------------
# Datasets catalogue + page-gate RBAC
# ---------------------------------------------------------------------------

def test_datasets_catalogue_shape(test_client, make_user, auth_headers):
    facility = _facility()
    clinician = make_user(role="clinician", facility=facility)
    resp = test_client.get("/reports/datasets", headers=auth_headers(clinician))
    assert resp.status_code == 200, resp.text
    keys = {d["key"] for d in resp.json()}
    assert keys == {"encounters", "admissions", "ancillary_results", "conditions", "bills"}
    encounters = next(d for d in resp.json() if d["key"] == "encounters")
    assert encounters["fields"]["encounter_type"]["type"] == "enum"
    assert encounters["fields"]["encounter_type"]["groupable"] is True
    assert "outpatient" in encounters["fields"]["encounter_type"]["options"]


def test_reporting_page_not_granted_to_receptionist_by_default(test_client, make_user, auth_headers):
    facility = _facility()
    receptionist = make_user(role="receptionist", facility=facility)
    resp = test_client.get("/reports/datasets", headers=auth_headers(receptionist))
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Facility scoping + filter/field validation
# ---------------------------------------------------------------------------

def test_run_encounters_is_facility_scoped(test_client, make_user, auth_headers, db_session):
    facility_a, facility_b = _facility("A"), _facility("B")
    patient = _make_patient(db_session)
    _encounter(db_session, patient.id, facility_a, reason="A's visit")
    _encounter(db_session, patient.id, facility_b, reason="B's visit")

    clinician_a = make_user(role="clinician", facility=facility_a)
    resp = test_client.post(
        "/reports/run",
        json={"dataset": "encounters", "fields": ["reason", "started_at"]},
        headers=auth_headers(clinician_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    reasons = [row[0] for row in body["rows"]]
    assert reasons == ["A's visit"]


def test_run_unknown_field_is_422(test_client, make_user, auth_headers):
    facility = _facility()
    clinician = make_user(role="clinician", facility=facility)
    resp = test_client.post(
        "/reports/run", json={"dataset": "encounters", "fields": ["not_a_real_field"]},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 422


def test_run_unfilterable_field_in_filters_is_422(test_client, make_user, auth_headers):
    facility = _facility()
    clinician = make_user(role="clinician", facility=facility)
    # `reason` is a selectable field but not marked filterable=True.
    resp = test_client.post(
        "/reports/run", json={"dataset": "encounters", "filters": {"reason": "x"}},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 422


def test_run_enum_filter(test_client, make_user, auth_headers, db_session):
    facility = _facility()
    patient = _make_patient(db_session)
    _encounter(db_session, patient.id, facility, encounter_type="outpatient")
    _encounter(db_session, patient.id, facility, encounter_type="emergency")

    clinician = make_user(role="clinician", facility=facility)
    resp = test_client.post(
        "/reports/run",
        json={"dataset": "encounters", "fields": ["encounter_type"], "filters": {"encounter_type": ["emergency"]}},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 200, resp.text
    assert [row[0] for row in resp.json()["rows"]] == ["emergency"]


# ---------------------------------------------------------------------------
# Group-by aggregation (ancillary TAT)
# ---------------------------------------------------------------------------

def test_group_by_module_computes_avg_tat(test_client, make_user, auth_headers, db_session):
    facility = _facility()
    patient = _make_patient(db_session)
    now = datetime.now(timezone.utc)

    req1 = _service_request(db_session, patient.id, facility, module="laboratory", created_at=now - timedelta(minutes=30))
    _service_result(db_session, req1, performed_at=now)
    req2 = _service_request(db_session, patient.id, facility, module="laboratory", created_at=now - timedelta(minutes=10))
    _service_result(db_session, req2, performed_at=now)
    req3 = _service_request(db_session, patient.id, facility, module="xray", created_at=now - timedelta(minutes=60))
    _service_result(db_session, req3, performed_at=now)

    clinician = make_user(role="clinician", facility=facility)
    resp = test_client.post(
        "/reports/run",
        json={"dataset": "ancillary_results", "fields": ["module", "tat_minutes"], "group_by": ["module"]},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    col_keys = [c["key"] for c in body["columns"]]
    assert col_keys == ["module", "count", "avg_tat_minutes"]
    by_module = {row[0]: row for row in body["rows"]}
    assert by_module["laboratory"][1] == 2  # count
    assert by_module["laboratory"][2] == 20.0  # avg of 30 and 10
    assert by_module["xray"][1] == 1
    assert by_module["xray"][2] == 60.0


def test_group_by_requires_groupable_field(test_client, make_user, auth_headers):
    facility = _facility()
    clinician = make_user(role="clinician", facility=facility)
    # `reason` is not groupable.
    resp = test_client.post(
        "/reports/run", json={"dataset": "encounters", "group_by": ["reason"]},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def test_export_pdf_and_excel(test_client, make_user, auth_headers, db_session):
    facility = _facility()
    patient = _make_patient(db_session)
    _encounter(db_session, patient.id, facility, reason="Export check")
    clinician = make_user(role="clinician", facility=facility)

    pdf_resp = test_client.post(
        "/reports/export", json={"dataset": "encounters", "fields": ["reason"], "format": "pdf"},
        headers=auth_headers(clinician),
    )
    assert pdf_resp.status_code == 200, pdf_resp.text
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert pdf_resp.content[:4] == b"%PDF"

    xlsx_resp = test_client.post(
        "/reports/export", json={"dataset": "encounters", "fields": ["reason"], "format": "excel"},
        headers=auth_headers(clinician),
    )
    assert xlsx_resp.status_code == 200, xlsx_resp.text
    assert xlsx_resp.content[:2] == b"PK"  # .xlsx is a zip container

    bad_resp = test_client.post(
        "/reports/export", json={"dataset": "encounters", "format": "csv"},
        headers=auth_headers(clinician),
    )
    assert bad_resp.status_code == 422


# ---------------------------------------------------------------------------
# Saved templates: visibility, sharing, delete permission
# ---------------------------------------------------------------------------

def test_template_private_by_default_then_shared(test_client, make_user, auth_headers):
    facility = _facility()
    owner = make_user(role="clinician", facility=facility)
    other = make_user(role="records_officer", facility=facility)

    create = test_client.post(
        "/reports/templates",
        json={"name": "My private view", "dataset": "encounters", "fields": ["reason"]},
        headers=auth_headers(owner),
    )
    assert create.status_code == 201, create.text
    template_id = create.json()["id"]
    assert create.json()["editable"] is True

    # Not visible to a different user at the same facility yet.
    listing = test_client.get("/reports/templates", headers=auth_headers(other)).json()
    assert template_id not in {t["id"] for t in listing}
    other_get_delete = test_client.delete(f"/reports/templates/{template_id}", headers=auth_headers(other))
    assert other_get_delete.status_code == 404  # hidden, not merely forbidden

    # Owner can see it, and it reports non-editable=False correctly for other.
    own_listing = test_client.get("/reports/templates", headers=auth_headers(owner)).json()
    assert template_id in {t["id"] for t in own_listing}


def test_template_shared_visible_but_only_owner_or_admin_can_delete(test_client, make_user, auth_headers):
    facility = _facility()
    owner = make_user(role="clinician", facility=facility)
    other = make_user(role="records_officer", facility=facility)
    admin = make_user(role="admin", facility=facility)

    create = test_client.post(
        "/reports/templates",
        json={"name": "Shared view", "dataset": "encounters", "fields": ["reason"], "is_shared": True},
        headers=auth_headers(owner),
    )
    template_id = create.json()["id"]

    listing = test_client.get("/reports/templates", headers=auth_headers(other)).json()
    row = next(t for t in listing if t["id"] == template_id)
    assert row["editable"] is False

    forbidden = test_client.delete(f"/reports/templates/{template_id}", headers=auth_headers(other))
    assert forbidden.status_code == 403

    ok = test_client.delete(f"/reports/templates/{template_id}", headers=auth_headers(admin))
    assert ok.status_code == 204


def test_template_invalid_selection_rejected_at_save(test_client, make_user, auth_headers):
    facility = _facility()
    clinician = make_user(role="clinician", facility=facility)
    resp = test_client.post(
        "/reports/templates",
        json={"name": "Bad", "dataset": "encounters", "fields": ["not_a_field"]},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# P3.7: period-bucket fields + anonymization
# ---------------------------------------------------------------------------

def test_period_bucket_groups_by_day(test_client, make_user, auth_headers, db_session):
    facility = _facility()
    patient = _make_patient(db_session)
    day = datetime(2026, 3, 5, 9, 0, tzinfo=timezone.utc)
    _encounter(db_session, patient.id, facility, started_at=day)
    _encounter(db_session, patient.id, facility, started_at=day.replace(hour=15))
    _encounter(db_session, patient.id, facility, started_at=day + timedelta(days=1))

    clinician = make_user(role="clinician", facility=facility)
    resp = test_client.post(
        "/reports/run",
        json={"dataset": "encounters", "fields": ["started_at_day"], "group_by": ["started_at_day"]},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 200, resp.text
    by_day = {row[0]: row[1] for row in resp.json()["rows"]}
    assert by_day["2026-03-05"] == 2
    assert by_day["2026-03-06"] == 1


def test_anonymize_replaces_pii_fields_only(test_client, make_user, auth_headers, db_session):
    facility = _facility()
    patient = _make_patient(db_session, full_name="Ah Kow")
    _encounter(db_session, patient.id, facility, encounter_type="outpatient")

    clinician = make_user(role="clinician", facility=facility)
    resp = test_client.post(
        "/reports/run",
        json={"dataset": "encounters", "fields": ["patient_name", "encounter_type"], "anonymize": True},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 200, resp.text
    row = resp.json()["rows"][0]
    assert row[0] != "Ah Kow"
    assert row[0].startswith("Case-")
    assert row[1] == "outpatient"  # non-PII field untouched


def test_anonymized_pseudonym_is_keyed_not_a_plain_hash(test_client, make_user, auth_headers, db_session):
    import hashlib
    facility = _facility()
    patient = _make_patient(db_session, full_name="Ah Kow")
    _encounter(db_session, patient.id, facility, encounter_type="outpatient")
    clinician = make_user(role="clinician", facility=facility)
    resp = test_client.post(
        "/reports/run", json={"dataset": "encounters", "fields": ["patient_name"], "anonymize": True},
        headers=auth_headers(clinician))
    assert resp.json()["rows"][0][0] != "Case-" + hashlib.sha256(b"Ah Kow").hexdigest()[:8]


def test_anonymized_groups_below_the_minimum_cell_are_dropped(test_client, make_user, auth_headers, db_session):
    facility = _facility()
    patient = _make_patient(db_session, full_name="Cell Pat")
    for _ in range(5):
        _encounter(db_session, patient.id, facility, encounter_type="outpatient")
    _encounter(db_session, patient.id, facility, encounter_type="emergency")  # a group of one
    clinician = make_user(role="clinician", facility=facility)
    body = {"dataset": "encounters", "fields": ["encounter_type"], "group_by": ["encounter_type"]}

    plain = test_client.post("/reports/run", json=body, headers=auth_headers(clinician)).json()
    assert {r[0] for r in plain["rows"]} == {"outpatient", "emergency"}

    anon = test_client.post("/reports/run", json={**body, "anonymize": True}, headers=auth_headers(clinician)).json()
    assert [r[0] for r in anon["rows"]] == ["outpatient"]
    assert anon["suppressed_groups"] == 1 and anon["row_count"] == 1


def test_dataset_specs_expose_pii_flag(test_client, make_user, auth_headers):
    facility = _facility()
    clinician = make_user(role="clinician", facility=facility)
    resp = test_client.get("/reports/datasets", headers=auth_headers(clinician))
    encounters = next(d for d in resp.json() if d["key"] == "encounters")
    assert encounters["fields"]["patient_name"]["pii"] is True
    assert encounters["fields"]["encounter_type"]["pii"] is False


# ---------------------------------------------------------------------------
# P3.7: notifiable disease reporting workflow
# ---------------------------------------------------------------------------

def test_notifiable_disease_full_workflow(test_client, make_user, auth_headers, db_session):
    facility = _facility()
    patient = _make_patient(db_session, full_name="Case Patient")
    condition = _condition(db_session, patient.id, facility, name="Dengue Fever (confirmed)")
    clinician = make_user(role="clinician", facility=facility)
    headers = auth_headers(clinician)

    candidates = test_client.get("/reports/notifiable-diseases/candidates", headers=headers).json()
    match = next(c for c in candidates if c["condition_id"] == condition.id)
    assert match["matched_disease"] == "Dengue Fever"
    assert match["patient_name"] == "Case Patient"

    create = test_client.post(
        "/reports/notifiable-diseases",
        json={"patient_id": patient.id, "condition_id": condition.id, "disease_name": "Dengue Fever", "onset_date": "2026-03-01"},
        headers=headers,
    )
    assert create.status_code == 201, create.text
    report_id = create.json()["id"]
    assert create.json()["status"] == "pending"
    assert create.json()["patient_name"] == "Case Patient"

    # No longer suggested once filed.
    candidates_after = test_client.get("/reports/notifiable-diseases/candidates", headers=headers).json()
    assert condition.id not in {c["condition_id"] for c in candidates_after}

    # Duplicate filing against the same condition is rejected.
    dup = test_client.post(
        "/reports/notifiable-diseases",
        json={"patient_id": patient.id, "condition_id": condition.id, "disease_name": "Dengue Fever"},
        headers=headers,
    )
    assert dup.status_code == 409

    doc = test_client.get(f"/reports/notifiable-diseases/{report_id}/document", headers=headers)
    assert doc.status_code == 200, doc.text
    assert doc.content[:4] == b"%PDF"

    submitted = test_client.post(f"/reports/notifiable-diseases/{report_id}/submitted", headers=headers)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["submitted_at"] is not None

    resubmit = test_client.post(f"/reports/notifiable-diseases/{report_id}/submitted", headers=headers)
    assert resubmit.status_code == 409


def test_notifiable_disease_free_text_not_gated_on_suggestion_list(test_client, make_user, auth_headers, db_session):
    facility = _facility()
    patient = _make_patient(db_session)
    clinician = make_user(role="clinician", facility=facility)
    resp = test_client.post(
        "/reports/notifiable-diseases",
        json={"patient_id": patient.id, "disease_name": "Some Emerging Illness Not On The List"},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 201, resp.text


def test_notifiable_disease_is_facility_scoped(test_client, make_user, auth_headers, db_session):
    facility_a, facility_b = _facility("A"), _facility("B")
    patient = _make_patient(db_session)
    condition = _condition(db_session, patient.id, facility_a, name="Cholera")

    clinician_b = make_user(role="clinician", facility=facility_b)
    candidates_b = test_client.get("/reports/notifiable-diseases/candidates", headers=auth_headers(clinician_b)).json()
    assert condition.id not in {c["condition_id"] for c in candidates_b}

    clinician_a = make_user(role="clinician", facility=facility_a)
    create = test_client.post(
        "/reports/notifiable-diseases",
        json={"patient_id": patient.id, "condition_id": condition.id, "disease_name": "Cholera"},
        headers=auth_headers(clinician_a),
    )
    report_id = create.json()["id"]

    # Facility B cannot see or act on facility A's notification.
    assert test_client.get(f"/reports/notifiable-diseases/{report_id}/document", headers=auth_headers(clinician_b)).status_code == 404
    assert test_client.post(f"/reports/notifiable-diseases/{report_id}/submitted", headers=auth_headers(clinician_b)).status_code == 404


# ---------------------------------------------------------------------------
# NL report narrative (P4.3c)
# ---------------------------------------------------------------------------

def test_narrative_uses_local_llm_over_the_run_result(test_client, make_user, auth_headers, db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ai.report_narrative.generate_text",
        lambda *a, **kw: "Most visits this period were outpatient.",
    )
    facility = _facility()
    patient = _make_patient(db_session)
    _encounter(db_session, patient.id, facility, encounter_type="outpatient")
    clinician = make_user(role="clinician", facility=facility)

    resp = test_client.post(
        "/reports/narrative",
        json={"dataset": "encounters", "fields": ["encounter_type"]},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["narrative"] == "Most visits this period were outpatient."
    assert "not a substitute" in body["disclaimer"].lower()


def test_narrative_falls_back_to_none_without_ollama(test_client, make_user, auth_headers, db_session, monkeypatch):
    monkeypatch.setattr("app.ai.report_narrative.generate_text", lambda *a, **kw: None)
    facility = _facility()
    patient = _make_patient(db_session)
    _encounter(db_session, patient.id, facility)
    clinician = make_user(role="clinician", facility=facility)

    resp = test_client.post(
        "/reports/narrative", json={"dataset": "encounters", "fields": ["reason"]},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["narrative"] is None


def test_narrative_skips_the_llm_when_no_rows(test_client, make_user, auth_headers, monkeypatch):
    calls = []
    monkeypatch.setattr("app.ai.report_narrative.generate_text", lambda *a, **kw: calls.append(1))
    facility = _facility()
    clinician = make_user(role="clinician", facility=facility)

    resp = test_client.post(
        "/reports/narrative", json={"dataset": "encounters", "fields": ["reason"]},
        headers=auth_headers(clinician),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["narrative"] is None
    assert calls == []  # no rows -> never even asked the LLM


def test_narrative_requires_reporting_role(test_client, make_user, auth_headers):
    facility = _facility()
    receptionist = make_user(role="receptionist", facility=facility)
    resp = test_client.post(
        "/reports/narrative", json={"dataset": "encounters", "fields": ["reason"]},
        headers=auth_headers(receptionist),
    )
    assert resp.status_code == 403


def test_excel_export_survives_forbidden_sheet_title_chars():
    """Dataset labels such as "A / B" used to 500 openpyxl's sheet-title setter."""
    import io
    import openpyxl
    from app import report_export

    result = {"columns": [{"key": "n", "label": "N"}], "rows": [[1]]}
    for title in ("Visits / Encounters", "a\b?c*d[e]f:g", "'quoted'", "x" * 80, "///"):
        wb = openpyxl.load_workbook(io.BytesIO(report_export.render_excel(title, result)))
        name = wb.active.title
        assert 0 < len(name) <= 31 and not any(ch in name for ch in "\/?*[]:")


def test_report_timestamps_are_ddmmyyyy_hhmm_malaysia_time():
    from datetime import datetime, timezone
    from app.report_export import _fmt_dt

    # 15:24 UTC is 23:24 in Kuala Lumpur (UTC+8, no DST); 24-hour clock, zero padded
    assert _fmt_dt(datetime(2026, 10, 10, 15, 24, 40, tzinfo=timezone.utc)) == "10-10-2026 23:24"
    assert _fmt_dt("2026-10-10T15:24:40.123456+00:00") == "10-10-2026 23:24"
    assert _fmt_dt(datetime(2026, 1, 5, 0, 7)) == "05-01-2026 08:07"  # naive = UTC
    assert _fmt_dt(None) == "-"
