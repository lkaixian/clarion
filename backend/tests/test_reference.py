def test_reference_lists(test_client, make_user, auth_headers):
    h = auth_headers(make_user(role="clinician"))
    kinds = test_client.get("/reference", headers=h).json()
    assert kinds["states"] == 14 and kinds["postcodes"] == 443
    pc = test_client.get("/reference/postcodes?parent=batu_pahat", headers=h).json()
    assert pc and all(r["parent"] == "batu_pahat" for r in pc)
    assert test_client.get("/reference/nope", headers=h).status_code == 404


def test_filter_matches_parent_and_state_names(test_client, make_user, auth_headers):
    h = auth_headers(make_user(role="clinician"))
    batu = test_client.get("/reference/postcodes?q=batu pahat", headers=h).json()
    assert batu and all(r["parent"] == "batu_pahat" and r["parent_name"] == "Batu Pahat" for r in batu)
    # the state is a grandparent: typing its name finds the postcodes in it
    johor = test_client.get("/reference/postcodes?q=johor", headers=h).json()
    assert len(johor) >= len(batu) and all(r["state_name"] and "Johor" in r["state_name"] for r in johor)
    # every word has to match something on the row
    both = test_client.get("/reference/postcodes?q=batu pahat 83020", headers=h).json()
    assert [r["code"] for r in both] == ["83020"]
    assert test_client.get("/reference/postcodes?q=zzzzqq", headers=h).json() == []
    # plain name search still works on a list with no parents
    assert any(r["code"] == "johor" for r in test_client.get("/reference/states?q=johor", headers=h).json())


def test_drug_and_product_search_match_their_category(test_client, make_user, auth_headers):
    h = auth_headers(make_user(role="clinician"))
    by_code = test_client.get("/drugs?q=A01&limit=5", headers=h).json()
    cat = next(c for c in test_client.get("/reference/drug_categories", headers=h).json() if c["code"] == "A01")
    by_class = test_client.get(f"/drugs?q={cat['name']}&limit=200", headers=h).json()
    assert by_class and all(d["drug_code"].startswith("A01") for d in by_class[:5]) and by_code is not None
    hospital = test_client.get("/products?q=Laboratory&limit=5", headers=h).json()
    assert hospital and all(p["category_code"] == "lab" or "laboratory" in p["product_name"].lower() for p in hospital)
