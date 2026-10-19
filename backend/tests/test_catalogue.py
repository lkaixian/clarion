def _h(auth_headers, make_user):
    return auth_headers(make_user(role="clinician"))


def test_drug_search_and_detail(test_client, make_user, auth_headers):
    h = _h(auth_headers, make_user)
    hits = test_client.get("/drugs?q=triamcinolone&limit=5", headers=h).json()
    assert hits and all("triamcinolone" in (d["drug_generic_name"] + (d["active_ingredient"] or "")).lower()
                        for d in hits)
    d = test_client.get(f"/drugs/{hits[0]['drug_code']}", headers=h).json()
    assert d["drug_code"] == hits[0]["drug_code"] and d["category_name"]
    # a drug with default prescribing lines resolves codes to names
    rx = test_client.get("/drugs/J05AR02964T1001XX", headers=h).json()
    assert rx["prescriptions"] and rx["prescriptions"][0]["frequency"] != "OD"
    assert rx["indications"]
    assert test_client.get("/drugs/NOPE", headers=h).status_code == 404


def test_drug_paging_and_category(test_client, make_user, auth_headers):
    h = _h(auth_headers, make_user)
    p1 = test_client.get("/drugs?limit=3", headers=h).json()
    p2 = test_client.get("/drugs?limit=3&offset=3", headers=h).json()
    assert len(p1) == 3 and len(p2) == 3 and not {d["drug_code"] for d in p1} & {d["drug_code"] for d in p2}
    a01 = test_client.get("/drugs?category=A01&limit=50", headers=h).json()
    assert a01 and all(d["drug_code"].startswith("A01") for d in a01)
    assert test_client.get("/drugs?limit=500", headers=h).status_code == 422


def test_product_search_detail_uoms(test_client, make_user, auth_headers):
    h = _h(auth_headers, make_user)
    hit = test_client.get("/products?q=alcohol swab", headers=h).json()
    assert hit and hit[0]["product_code"] == "10200001"
    full = test_client.get("/products/15010001", headers=h).json()
    assert full["uoms"] and full["uoms"][0]["unit_code"] == "unit"
    assert test_client.get("/products/NOPE", headers=h).status_code == 404


def test_catalogue_requires_login(test_client):
    assert test_client.get("/drugs").status_code in (401, 403)
    assert test_client.get("/products").status_code in (401, 403)
    assert test_client.get("/reference").status_code in (401, 403)


def test_dictionaries_in_reference(test_client, make_user, auth_headers):
    h = _h(auth_headers, make_user)
    k = test_client.get("/reference", headers=h).json()
    assert k["drug_routes"] == 40 and k["product_categories"] == 12 and k["drug_indications"] == 330
    cities = test_client.get("/reference/drug_categories?parent=A", headers=h).json()
    assert cities and all(c["parent"] == "A" for c in cities)




def test_patient_accounts_are_refused(test_client, make_user, auth_headers):
    h = auth_headers(make_user(role="patient"))
    for url in ("/drugs", "/products", "/reference", "/reference/states"):
        assert test_client.get(url, headers=h).status_code == 403


def test_fee_schedules_search_part_and_paging(test_client, make_user, auth_headers):
    h = auth_headers(make_user(role="clinician"))
    hit = test_client.get("/fee-schedules?q=first visit&limit=5", headers=h).json()
    assert hit and all("first visit" in (r["sub_header"] + r["description"]).lower() for r in hit)
    part_i = test_client.get("/fee-schedules?part=I&limit=200", headers=h).json()
    assert part_i and all(r["part"] == "I" for r in part_i)
    p1 = test_client.get("/fee-schedules?limit=3", headers=h).json()
    p2 = test_client.get("/fee-schedules?limit=3&offset=3", headers=h).json()
    assert not {r["fee_code"] for r in p1} & {r["fee_code"] for r in p2}
    assert any("-" in (r["value"] or "") for r in part_i)  # fee ranges stay as text


def test_price_tiers_by_charge_code(test_client, make_user, auth_headers):
    h = auth_headers(make_user(role="pharmacist"))
    all_t = test_client.get("/price-tiers", headers=h).json()
    assert len(all_t) == 128
    t = test_client.get("/price-tiers?charge_code=tablet_brand", headers=h).json()
    assert t and all(x["charge_code"] == "tablet_brand" for x in t)
    assert t[0]["rates"] and "tier_outpatient" in t[0]["rates"]
    assert test_client.get("/price-tiers?charge_code=nope", headers=h).json() == []


def test_ward_bed_and_misc_dictionaries(test_client, make_user, auth_headers):
    h = auth_headers(make_user(role="clinician"))
    k = test_client.get("/reference", headers=h).json()
    assert k["his_beds"] == 6 and k["his_wards"] == 6 and k["bed_statuses"] == 5 and k["triages"] == 4
    beds = test_client.get("/reference/his_beds?parent=ward_01", headers=h).json()
    assert beds and beds[0]["extra"]["class_code"] == "class_1"
    assert test_client.get("/reference/ward_classes", headers=h).json()[0]["extra"]["class_price"] == 300
    # trailing blanks / mojibake NBSP were stripped from codes
    charges = test_client.get("/reference/product_charges", headers=h).json()
    assert charges and all(c["code"] == c["code"].strip() and "\u00c2" not in c["code"] for c in charges)


def test_new_endpoints_refuse_patients(test_client, make_user, auth_headers):
    h = auth_headers(make_user(role="patient"))
    assert test_client.get("/fee-schedules", headers=h).status_code == 403
    assert test_client.get("/price-tiers", headers=h).status_code == 403
