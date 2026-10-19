"""Extract HIS lookup and catalogue tables from his_open_1.sql into app/*.json.

    python db/gen_reference_data.py ../../his_open_1.sql

reference_data.json   all ref_* lists                (migration 0f1a7c3d9b52)
reference_data_2.json drug/product/store dictionaries (migration 1b2c4d6e8f10)
reference_data_3.json ward/bed/diet/misc dictionaries (migration 2c3d5e7f9a11)
his_data/<table>.json typed catalogue tables {cols, rows} (same migration)

Dictionary row shape: [kind, code, name, parent, extra]. code = first column, name = first
column containing name/english/description (else the second), parent = state_code /
system_code / parent_code when present, the rest (minus timestamps) goes to extra.
ref_sets is skipped (per-user shortcuts). product_uoms keeps 1,574 rows whose product_code\nis a fee_schedules code (FS...), so it has no FK to products.
"""
import json
import re
import sys
from pathlib import Path

SKIP = {"ref_sets"}
DICT2 = {
    "drug_categories", "drug_dosages", "drug_frequencies", "drug_routes", "drug_instructions",
    "drug_cautions", "drug_special_instructions", "drug_indications", "drug_systems",
    "product_categories", "product_category_parents", "product_types", "product_charges",
    "stock_tags", "stores", "departments", "payment_methods", "tax_codes", "tax_types",
}
DICT3 = {
    "ward_rooms", "ward_classes", "bed_statuses", "bed_transactions", "wards", "beds", "diets",
    "diet_classes", "diet_contaminations", "diet_enterals", "diet_meals", "diet_periods",
    "diet_ratings", "diet_textures", "diet_therapeutics", "loan_types", "document_types",
    "document_statuses", "credit_cards", "triages", "patient_classifications", "order_forms",
    "form_systems", "stock_movements", "purchase_documents", "purchase_request_statuses",
}
# HIS wards/beds are a different thing from CLARION wards/admissions; keep them apart by name.
RENAME = {"wards": "his_wards", "beds": "his_beds"}
# typed table -> columns kept (timestamps dropped), in his_open order
TYPED = {
    "drugs": ["drug_code", "drug_generic_name", "drug_label", "active_ingredient", "drug_category",
              "drug_schedule", "drug_formulary", "drug_type", "item_subgroup", "trade_name", "strength",
              "uom_strength", "dosage_form", "sku_uom", "special_code", "instruction_code", "caution_code"],
    "drug_prescriptions": ["prescription_id", "drug_code", "drug_dosage", "dosage_code", "frequency_code",
                           "route_code", "drug_duration", "period_code", "drug_total_unit",
                           "instruction_code", "special_code", "caution_code"],
    "drug_diseases": ["disease_id", "drug_code", "indication_code"],
    "products": ["product_code", "product_name", "product_name_other", "product_custom_id", "category_code",
                 "unit_code", "order_form", "product_unit_charge", "product_stocked", "product_edit_price",
                 "product_reorder", "product_input_tax", "form_code", "product_average_cost", "charge_code",
                 "product_output_tax", "status_code", "product_track_batch", "product_on_hand",
                 "product_drop_charge", "product_local_store", "product_non_claimable",
                 "product_duration_use"],
    "fee_schedules": ["fee_code", "part", "header", "sub_header", "description", "value", "value2", "deleted_at"],
    "product_price_tiers": None,  # reshaped: tier_id, charge_code, tier_min, tier_max, rates{...}
    "product_uoms": ["id", "product_code", "unit_code", "uom_rate", "uom_price", "uom_price_2", "uom_cost",
                     "uom_default_cost", "uom_default_price"],
}
TS = {"created_at", "updated_at", "deleted_at"}
PARENTS = ("state_code", "system_code", "parent_code", "ward_code", "diet_code")
INSERT = re.compile(r"insert\s+into `(\w+)`\(([^)]*)\)\s*values\s*(.*?);\s*$", re.S | re.M | re.I)
TOKEN = re.compile(r"'((?:[^'\\]|\\.)*)'|(NULL)|(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)")


def clean(s):
    """Source codes carry trailing blanks and a mojibake NBSP (UTF-8 read as latin-1)."""
    return s.replace("\u00c2\u00a0", " ").replace("\u00a0", " ").strip() if isinstance(s, str) else s


def num(s: str):
    return float(s) if re.search(r"[.eE]", s) else int(s)


def tuples(body: str):
    """Yield each (...) row of a VALUES list as a python list (numbers typed, NULL -> None)."""
    for m in re.finditer(r"\(((?:'(?:[^'\\]|\\.)*'|[^()'])*)\)", body):
        row = []
        for s, null, n in TOKEN.findall(m.group(1)):
            row.append(None if null else num(n) if n else re.sub(r"\\(.)", r"\1", s))
        yield row


def dict_rows(kind: str, cols: list, row: list):
    r = dict(zip(cols, row))
    code = row[0]
    name = next((c for c in cols[1:] if re.search(r"name|english|description", c)), cols[1])
    parent_col = next((c for c in PARENTS if c in r and c != cols[0]), None)
    if kind == "ref_postcodes":
        code, name, parent_col = r["postcode"], "postcode", "city_code"
        used = {"id", "postcode", "city_code"}
    else:
        used = {cols[0], name, parent_col}
    extra = {k: v for k, v in r.items() if k not in used and k not in TS and v is not None}
    parent = r.get(parent_col) if parent_col else None
    label = r[name] if kind != "ref_postcodes" else r["postcode"]
    short = RENAME.get(kind, kind.removeprefix("ref_"))
    return [short, clean(str(code)), clean(str(label if label is not None else "")),
            None if parent is None else clean(str(parent)), extra or None]


def main(path: str) -> None:
    sql = Path(path).read_text(encoding="utf-8", errors="replace")
    app = Path(__file__).resolve().parent.parent / "app"
    (app / "his_data").mkdir(exist_ok=True)
    ref, dic, dic3 = [], [], []
    drug_codes: set = set()  # drugs is processed first (sorted below)
    for kind, cols, body in sorted(INSERT.findall(sql), key=lambda m: m[0] != "drugs"):
        cols = [c.strip("` ") for c in cols.split(",")]
        if kind in TYPED:
            if kind == "product_price_tiers":
                head = ["tier_id", "charge_code", "tier_min", "tier_max"]
                tcols = head + ["rates"]
                rows = []
                for r in tuples(body):
                    d = dict(zip(cols, r))
                    rates = {k: v for k, v in d.items() if k not in head and k not in TS and v is not None}
                    rows.append([clean(d[h]) if h == "charge_code" else d[h] for h in head] + [rates or None])
            else:
                tcols = TYPED[kind]
                keep = [cols.index(c) for c in tcols]
                rows = [[r[i] for i in keep] for r in tuples(body)]
            if kind in ("drug_prescriptions", "drug_diseases"):  # source has 1 orphan junk row each
                rows = [r for r in rows if r[1] in drug_codes]
            if kind == "drug_diseases":  # rows with no indication carry no information
                rows = [r for r in rows if r[2] is not None]
            if kind == "drugs":
                drug_codes.update(r[0] for r in rows)
            if kind == "fee_schedules":  # drop soft-deleted rows, then the marker column
                rows = [r[:-1] for r in rows if r[-1] is None]
                tcols = tcols[:-1]
            (app / "his_data" / f"{kind}.json").write_text(
                json.dumps({"cols": tcols, "rows": rows}, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8")
            print(f"{kind}: {len(rows)} rows")
        elif kind.startswith("ref_") and kind not in SKIP:
            ref += [dict_rows(kind, cols, r) for r in tuples(body)]
        elif kind in DICT2:
            dic += [dict_rows(kind, cols, r) for r in tuples(body)]
        elif kind in DICT3:
            dic3 += [dict_rows(kind, cols, r) for r in tuples(body)]
    for name, data in (("reference_data.json", ref), ("reference_data_2.json", dic), ("reference_data_3.json", dic3)):
        (app / name).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"{name}: {len(data)} rows, {len({r[0] for r in data})} kinds")


if __name__ == "__main__":
    main(sys.argv[1])





