"""Charge master Excel import: dry run, commit, duplicates, all-or-nothing, RBAC, scoping."""
import io

from openpyxl import Workbook

from app import models
from conftest import _facility

URL = "/billing/charge-master/import"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _book(rows, header=("category", "code", "name", "price", "active")):
    wb = Workbook()
    ws = wb.active
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _post(client, headers, raw, **params):
    return client.post(URL, params=params, headers=headers, files={"file": ("cm.xlsx", raw, XLSX)})


def _names(db_session, facility):
    return {i.name for i in db_session.query(models.ChargeMasterItem).filter_by(facility_name=facility)}


def test_dry_run_writes_nothing_then_commit_appends(test_client, make_user, auth_headers, db_session):
    fac = _facility("Import A")
    user = make_user(role="records_officer", facility=fac)
    raw = _book([["consultation", "C1", "Imp Consult", 30, "yes"], ["misc", None, "Imp Report", "RM 50.50", None]])

    r = _post(test_client, auth_headers(user), raw)  # dry_run defaults to true
    assert r.status_code == 200
    body = r.json()
    assert body["would_add"] == 2 and body["committed"] is False and body["errors"] == []
    assert _names(db_session, fac) == set()

    r = _post(test_client, auth_headers(user), raw, dry_run="false")
    assert r.json()["added"] == 2
    rows = {i.name: i for i in db_session.query(models.ChargeMasterItem).filter_by(facility_name=fac)}
    assert rows["Imp Report"].unit_price_cents == 5050 and rows["Imp Report"].active is True

    r = _post(test_client, auth_headers(user), raw, dry_run="false")  # same file again: all duplicates
    assert r.json()["added"] == 0 and r.json()["skipped_duplicates"] == 2


def test_any_bad_row_blocks_everything(test_client, make_user, auth_headers, db_session):
    fac = _facility("Import B")
    user = make_user(role="admin", facility=fac)
    raw = _book([
        ["consultation", "", "Good Row", 10, ""],
        ["dental", "", "Bad category", 10, ""],
        ["misc", "", "Bad price", "1e999", ""],
        ["misc", "", "Three decimals", "1.001", ""],
        ["misc", "", "Negative", -1, ""],
    ])
    body = _post(test_client, auth_headers(user), raw, dry_run="false").json()
    assert body["committed"] is False and body["added"] == 0
    assert [e["row"] for e in body["errors"]] == [3, 4, 5, 6]
    assert _names(db_session, fac) == set()


def test_duplicates_against_global_and_within_file(test_client, make_user, auth_headers, db_session):
    fac = _facility("Import C")
    db_session.add(models.ChargeMasterItem(category="misc", code="G1", name="Global Thing",
                                           unit_price_cents=100, facility_name=None))
    db_session.commit()
    user = make_user(role="records_officer", facility=fac)
    raw = _book([
        ["misc", "g1", "Different name same code", 5, ""],   # dup of global by code
        ["misc", "", "global thing", 5, ""],                 # dup by name (no code on this side)
        ["misc", "N1", "New One", 5, ""],
        ["misc", "N1", "New One again", 5, ""],              # dup of the row above
    ])
    body = _post(test_client, auth_headers(user), raw, dry_run="false").json()
    assert (body["added"], body["skipped_duplicates"]) == (1, 3)
    assert _names(db_session, fac) == {"New One"}


def test_rbac_and_bad_files(test_client, make_user, auth_headers, db_session):
    fac = _facility("Import D")
    raw = _book([["misc", "", "X", 1, ""]])
    for role in ("receptionist", "clinician", "pharmacist"):
        u = make_user(role=role, facility=fac)
        assert _post(test_client, auth_headers(u), raw).status_code == 403
        assert test_client.get(URL + "-template", headers=auth_headers(u)).status_code == 403
    admin = make_user(role="admin", facility=fac)
    h = auth_headers(admin)
    assert _post(test_client, h, b"not a workbook").status_code == 422
    assert _post(test_client, h, _book([], header=("category", "name"))).status_code == 422  # price missing
    assert _post(test_client, h, _book([])).status_code == 422                               # no data rows
    t = test_client.get(URL + "-template", headers=h)
    assert t.status_code == 200 and t.content.startswith(b"PK")
    # the template itself imports cleanly
    assert _post(test_client, h, t.content, dry_run="false").json()["added"] == 2


def test_huge_exponent_and_blank_padding(test_client, make_user, auth_headers, db_session):
    fac = _facility("Import E")
    h = auth_headers(make_user(role="admin", facility=fac))
    r = _post(test_client, h, _book([["misc", "", "Huge", "1e999999", ""]]))
    assert r.status_code == 200 and r.json()["error_count"] == 1  # reported, not a 500
    wb = Workbook()
    ws = wb.active
    ws.append(["category", "name", "price"])
    ws.append(["misc", "After padding", 3])
    for _ in range(2500):           # formatted-but-empty rows must not count as data rows
        ws.append([None, None, None])
    buf = io.BytesIO()
    wb.save(buf)
    body = _post(test_client, h, buf.getvalue()).json()
    assert body["would_add"] == 1 and body["error_count"] == 0
