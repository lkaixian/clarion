"""Smoke test for db/gen_data_dictionary.py (P5.4) -- catches breakage from
future SQLAlchemy upgrades or model changes (Computed/server_default columns
already broke this once, see git history)."""
from db.gen_data_dictionary import generate


def test_generate_covers_every_table_with_a_readable_erd():
    text = generate()
    assert "erDiagram" in text
    # spot-check tables from different corners of the schema, incl. one with
    # a Computed server_default (room_claims) and a plain int PK (audit_chain_state)
    for table in ("users", "patients", "room_claims", "audit_chain_state"):
        assert f"### `{table}`" in text
    # FK rendering didn't silently drop to empty
    assert "FK→users.id" in text or "FK→patients.id" in text
