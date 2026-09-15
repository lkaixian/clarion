"""Auto-generated DB schema documentation (P5.4, the tender).

Introspects `app.models`' live SQLAlchemy metadata -- not a hand-maintained
copy that drifts -- and writes a data dictionary + Mermaid ERD to
`docs/data-dictionary.md`. Re-run after any model change; there is nothing to
edit by hand here, `app/models.py` and the Alembic chain stay the only source
of truth.

Usage:
  python -m db.gen_data_dictionary
  python -m db.gen_data_dictionary --out some/other/path.md
"""
import argparse
import inspect
from pathlib import Path

from sqlalchemy import CheckConstraint, UniqueConstraint

from app import models  # noqa: F401 -- import registers every mapped table
from app.database import Base

BACKEND = Path(__file__).resolve().parent.parent
DEFAULT_OUT = BACKEND.parent / "docs" / "data-dictionary.md"


def _table_docstrings() -> dict:
    """table name -> its mapped class's docstring. Collapses whitespace
    WITHIN each paragraph but keeps blank-line paragraph breaks (rendered as
    real paragraph breaks in the output) -- code review 2026-09-15 caught an
    earlier version that joined the whole docstring into one line, mashing
    separate paragraphs into a single run-on sentence."""
    out = {}
    for mapper in Base.registry.mappers:
        raw = (mapper.class_.__doc__ or "").strip()
        if not raw:
            continue
        paragraphs = [" ".join(p.split()) for p in raw.split("\n\n")]
        out[mapper.local_table.name] = "\n\n".join(p for p in paragraphs if p)
    return out


def _col_type(col) -> str:
    try:
        return str(col.type)
    except Exception:
        return type(col.type).__name__


def _mermaid_erd(tables) -> str:
    """PK/FK columns only -- a diagram with every column of all 57 tables is
    unreadable; the per-table markdown below has the full column list."""
    lines = ["```mermaid", "erDiagram"]
    for t in tables:
        attrs = []
        for c in t.columns:
            base_type = _col_type(c).split("(")[0]
            if c.primary_key:
                attrs.append(f"        {base_type} {c.name} PK")
            elif c.foreign_keys:
                attrs.append(f"        {base_type} {c.name} FK")
        if attrs:
            lines.append(f"    {t.name} {{")
            lines.extend(attrs)
            lines.append("    }")
    # t.foreign_keys is a plain set -- ForeignKey doesn't define value-based
    # __hash__, so iteration order varies run-to-run and (code review
    # 2026-09-15) produced pure-reorder diffs on every regen. Sort explicitly
    # so re-running this script with no schema change produces an identical
    # file (the whole point of "auto-generated, not hand-maintained").
    seen = set()
    for t in tables:
        for fk in sorted(t.foreign_keys, key=lambda fk: (fk.parent.name, fk.column.table.name, fk.column.name)):
            other = fk.column.table.name
            key = (t.name, other, fk.parent.name)
            if key in seen:
                continue
            seen.add(key)
            lines.append(f'    {other} ||--o{{ {t.name} : "{fk.parent.name}"')
    lines.append("```")
    return "\n".join(lines)


def _default_repr(c) -> str:
    if c.default is not None:
        arg = getattr(c.default, "arg", c.default)
        if not callable(arg):
            return str(arg)
        if getattr(arg, "__name__", "") != "<lambda>":
            return arg.__name__
        # The dominant lambda default in this schema (66 columns) is the
        # "now, UTC" timestamp pattern -- rendering it as the literal string
        # "<lambda>" (code review 2026-09-15) told the reader nothing. Special-
        # cased rather than a general lambda-source parser: one other lambda
        # shape exists (a mutable-list default) and correctly falls through
        # to the generic "<lambda>" label below, which is honest, just terse.
        try:
            if "datetime.now(timezone.utc)" in inspect.getsource(arg):
                return "now (UTC)"
        except (OSError, TypeError):
            pass
        return "<lambda>"
    if c.server_default is not None:
        arg = getattr(c.server_default, "arg", None) or getattr(c.server_default, "sqltext", c.server_default)
        return f"server: {arg}"
    return ""


def _single_column_unique_names(t) -> set:
    """Column names covered by a single-column UniqueConstraint declared via
    __table_args__ -- NOT reflected in Column.unique (that flag only tracks
    unique=True passed directly to Column(...)). Code review 2026-09-15:
    room_claims's active_room_key/active_user_key are unique this way and
    rendered with a blank Notes cell without this."""
    out = set()
    for con in t.constraints:
        if isinstance(con, UniqueConstraint) and len(con.columns) == 1:
            out.add(next(iter(con.columns)).name)
    return out


def _table_constraint_notes(t) -> list:
    """Multi-column UniqueConstraint/CheckConstraint from __table_args__ --
    inherently not representable per-column (e.g. queue_tickets's
    (facility_name, queue_date, queue_number)), so listed once per table."""
    lines = []
    for con in t.constraints:
        if isinstance(con, UniqueConstraint) and len(con.columns) > 1:
            cols = ", ".join(c.name for c in con.columns)
            lines.append(f"- UNIQUE ({cols})" + (f" — `{con.name}`" if con.name else ""))
        elif isinstance(con, CheckConstraint):
            lines.append(f"- CHECK ({con.sqltext})" + (f" — `{con.name}`" if con.name else ""))
    return lines


def _table_md(t, doc: str) -> str:
    lines = [f"### `{t.name}`"]
    if doc:
        lines.append(f"\n{doc}\n")
    unique_single = _single_column_unique_names(t)
    lines.append("| Column | Type | Null | Key | Default | Notes |")
    lines.append("|---|---|---|---|---|---|")
    for c in t.columns:
        key = []
        if c.primary_key:
            key.append("PK")
        for fk in c.foreign_keys:
            key.append(f"FK→{fk.column.table.name}.{fk.column.name}")
        notes = []
        if c.unique or c.name in unique_single:
            notes.append("unique")
        if c.index:
            notes.append("indexed")
        lines.append(
            f"| {c.name} | {_col_type(c)} | {'YES' if c.nullable else 'NO'} | "
            f"{', '.join(key)} | {_default_repr(c)} | {', '.join(notes)} |"
        )
    constraint_notes = _table_constraint_notes(t)
    if constraint_notes:
        lines.append("\nTable-level constraints:\n")
        lines.extend(constraint_notes)
    return "\n".join(lines)


def generate() -> str:
    tables = list(Base.metadata.sorted_tables)  # FK-dependency order
    docs = _table_docstrings()
    parts = [
        "# CLARION -- Data Dictionary & ERD",
        "",
        "**Auto-generated** by `backend/db/gen_data_dictionary.py` from "
        "`app/models.py`'s live SQLAlchemy metadata -- tender clause "
        "**** (\"full documentation of DB schema and relationships\"). "
        "Do not hand-edit; re-run the script after any model change. "
        "Source of truth is always `app/models.py` + `backend/alembic/versions/`.",
        "",
        f"{len(tables)} tables.",
        "",
        "## Entity-Relationship Diagram",
        "",
        _mermaid_erd(tables),
        "",
        "## Tables",
        "",
    ]
    for t in tables:
        parts.append(_table_md(t, docs.get(t.name, "")))
        parts.append("")
    return "\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    out = Path(args.out)
    text = generate()
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({len(text)} bytes)")


if __name__ == "__main__":
    main()
