"""Drug catalogue linking: medications, inventory and purchase proposals carry drug_code."""
from app import models
from conftest import _facility, _make_patient


def _drug(db, code, generic, trade=None):
    db.merge(models.Drug(drug_code=code, drug_generic_name=generic, trade_name=trade))
    db.commit()


def _setup(db, make_user):
    fac = _facility("DrugLink")
    _drug(db, "ZZ-DL-1", "Zzquinol Tablet", "Zzquinol Brand")
    _drug(db, "ZZ-DL-2", "Twin Drug")
    _drug(db, "ZZ-DL-3", "Twin Drug")  # same name twice: ambiguous, must never auto-link
    p = _make_patient(db, full_name="Link Patient")
    db.add(models.Encounter(patient_id=p.id, facility_name=fac, encounter_type="outpatient"))
    db.commit()
    return fac, p, make_user(role="clinician", facility=fac), make_user(role="admin", facility=fac), \
        make_user(role="pharmacist", facility=fac)


def _meds(client, h, pid):
    return client.get(f"/patients/{pid}", headers=h).json()["medications"]


def test_medication_links_by_exact_name_code_or_stays_free_text(test_client, make_user, auth_headers, db_session):
    fac, p, doc, admin, pharm = _setup(db_session, make_user)
    h = auth_headers(doc)
    url = f"/patients/{p.id}/medications"
    assert test_client.post(url, headers=h, json={"drug_name": " zzquinol tablet "}).status_code == 200
    assert test_client.post(url, headers=h, json={"drug_name": "Twin Drug"}).status_code == 200      # ambiguous
    assert test_client.post(url, headers=h, json={"drug_name": "Herbal tea"}).status_code == 200      # not listed
    assert test_client.post(url, headers=h, json={"drug_name": "Mine", "drug_code": "ZZ-DL-3"}).status_code == 200
    assert test_client.post(url, headers=h, json={"drug_name": "X", "drug_code": "NOPE"}).status_code == 422
    codes = {m["drug_name"]: m["drug_code"] for m in _meds(test_client, h, p.id)}
    assert codes == {" zzquinol tablet ": "ZZ-DL-1", "Twin Drug": None, "Herbal tea": None, "Mine": "ZZ-DL-3"}


def test_rename_relinks_or_clears(test_client, make_user, auth_headers, db_session):
    fac, p, doc, admin, pharm = _setup(db_session, make_user)
    h = auth_headers(doc)
    ward = models.Ward(facility_name=fac, ward_name="W", total_beds=2)
    db_session.add(ward)
    db_session.flush()
    db_session.add(models.Admission(patient_id=p.id, facility_name=fac, ward_id=ward.id, bed_number=1))
    db_session.commit()  # present at the facility, so the amend guard allows the edit
    test_client.post(f"/patients/{p.id}/medications", headers=h, json={"drug_name": "Zzquinol Brand"})
    med = _meds(test_client, h, p.id)[0]
    assert med["drug_code"] == "ZZ-DL-1"
    r = test_client.patch(f"/patients/{p.id}/medications/{med['id']}", headers=h, json={"drug_name": "Something else"})
    assert r.status_code == 200 and r.json()["drug_code"] is None


def test_inventory_and_new_item_proposal_carry_code(test_client, make_user, auth_headers, db_session):
    fac, p, doc, admin, pharm = _setup(db_session, make_user)
    ha = auth_headers(admin)
    r = test_client.post("/admin/inventory", headers=ha, json={"drug_name": "Zzquinol Tablet", "unit": "tablets"})
    assert r.status_code == 200 and r.json()["drug_code"] == "ZZ-DL-1"
    item_id = r.json()["id"]
    r = test_client.patch(f"/admin/inventory/{item_id}", headers=ha, json={"drug_name": "Unlisted"})
    assert r.json()["drug_code"] is None
    assert test_client.post("/admin/inventory", headers=ha, json={"drug_name": "A", "drug_code": "NOPE"}).status_code == 422

    r = test_client.post("/pharmacy/purchase-proposals", headers=auth_headers(pharm),
                         json={"proposed_drug_name": "Zzquinol Brand", "quantity": 5})
    assert r.status_code == 202, r.text
    assert r.json()["drug_code"] == "ZZ-DL-1"
    r = test_client.post(f"/admin/purchase-proposals/{r.json()['id']}/approve", headers=ha)
    assert r.status_code == 200, r.text
    items = test_client.get("/admin/inventory", headers=ha).json()
    assert {i["drug_name"]: i["drug_code"] for i in items}["Zzquinol Brand"] == "ZZ-DL-1"


def test_patch_keeps_explicit_link_and_rejects_null_name(test_client, make_user, auth_headers, db_session):
    fac, p, doc, admin, pharm = _setup(db_session, make_user)
    ha = auth_headers(admin)
    r = test_client.post("/admin/inventory", headers=ha,
                         json={"drug_name": "Zzquinol 500mg tabs", "drug_code": "zz-dl-1".upper()})
    item = r.json()
    assert item["drug_code"] == "ZZ-DL-1"
    # editing only price/notes, with the same name echoed back, must not drop the link
    r = test_client.patch(f"/admin/inventory/{item['id']}", headers=ha,
                          json={"drug_name": "Zzquinol 500mg tabs", "unit_cost": 1.5})
    assert r.json()["drug_code"] == "ZZ-DL-1"
    assert test_client.patch(f"/admin/inventory/{item['id']}", headers=ha, json={"drug_name": None}).status_code == 422
