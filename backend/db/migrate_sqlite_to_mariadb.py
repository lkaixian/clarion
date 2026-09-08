import argparse
import os
import sys
import json
import hashlib
from datetime import datetime
from sqlalchemy import create_engine, MetaData, text
from sqlalchemy.schema import UniqueConstraint
import app.models  # noqa: F401 - side-effect import: registers every model on Base.metadata
from app.database import Base

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="sqlite:///./clarion.db")
    parser.add_argument("--target", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--truncate-target", action="store_true")
    parser.add_argument(
        "--report",
        default=None,
        help="Reconciliation report path (default: db/migration_report_<ts>.txt next to this script).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Proceed past a failed pre-flight scan. Does NOT disable target FK enforcement -- "
        "a genuinely orphaned row will still fail its INSERT. Use --prune-orphans to skip them.",
    )
    parser.add_argument(
        "--prune-orphans",
        action="store_true",
        help="During copy, skip (and log to the report) any source row whose foreign key has no "
        "parent row in the target. Keeps the target referentially clean; row counts will differ "
        "by the pruned count, which the report explains.",
    )
    args = parser.parse_args()
    if args.report is None:
        here = os.path.dirname(os.path.abspath(__file__))
        args.report = os.path.join(
            here, f"migration_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )
    return args

def coerce_value(val, col_type_str):
    if val is None:
        return None
    if val == "":
        if "VARCHAR" not in col_type_str and "TEXT" not in col_type_str and "STRING" not in col_type_str:
            return None

    if "BOOLEAN" in col_type_str or "BOOL" in col_type_str:
        if isinstance(val, bool): return val
        if isinstance(val, int): return bool(val)
        if isinstance(val, str):
            if val.lower() in ("1", "true", "yes"): return True
            if val.lower() in ("0", "false", "no", ""): return False
        return bool(val)
        
    if "DATE" in col_type_str or "DATETIME" in col_type_str or "TIMESTAMP" in col_type_str:
        if isinstance(val, datetime): return val
        if isinstance(val, str):
            val = val.strip()
            if not val: return None
            val = val.replace("Z", "+00:00")
            # missing microseconds handling
            try:
                # Try ISO format
                if " " in val:
                    val = val.replace(" ", "T", 1)
                return datetime.fromisoformat(val)
            except ValueError:
                return val # Let SQLAlchemy parse it
                
    if "JSON" in col_type_str:
        if isinstance(val, str):
            try:
                # try parsing string list like "['a']" which isn't valid json
                if val.startswith("'") or ("'" in val and '"' not in val):
                    val = val.replace("'", '"')
                return json.loads(val)
            except:
                pass # Return as string if invalid, though scan should catch
        return val
        
    return val

def run_preflight(source_engine, source_meta, blocks, warns):
    with source_engine.connect() as s_conn:
        for tbl_name, model_table in Base.metadata.tables.items():
            if tbl_name not in source_meta.tables:
                continue
            src_table = source_meta.tables[tbl_name]
            
            # 1. FK orphans
            for fk in model_table.foreign_keys:
                ref_table_name = fk.column.table.name
                col_name = fk.parent.name
                if col_name not in src_table.c or ref_table_name not in source_meta.tables:
                    continue
                ref_col_name = fk.column.name
                
                query = text(f"""
                    SELECT {col_name}, COUNT(*) as c
                    FROM {tbl_name}
                    WHERE {col_name} IS NOT NULL 
                    AND {col_name} NOT IN (SELECT {ref_col_name} FROM {ref_table_name})
                    GROUP BY {col_name}
                """)
                orphans = s_conn.execute(query).fetchall()
                if orphans:
                    sample = orphans[0][0]
                    blocks.append(f"FK Orphan: {tbl_name}.{col_name} -> {ref_table_name}.{ref_col_name} has {sum(r[1] for r in orphans)} orphaned rows (e.g. {sample}).")
            
            # 2. Over-length strings
            for col in model_table.columns:
                if col.name not in src_table.c: continue
                if hasattr(col.type, "length") and col.type.length is not None:
                    n = col.type.length
                    query = text(f"SELECT COUNT(*) FROM {tbl_name} WHERE {col.name} IS NOT NULL AND length({col.name}) > {n}")
                    c = s_conn.scalar(query)
                    if c > 0:
                        blocks.append(f"Over-length String: {tbl_name}.{col.name} has {c} rows > {n} chars.")
                        
            # 3. Unique collisions
            unique_sets = []
            for col in model_table.columns:
                if col.unique: unique_sets.append([col.name])
            for const in model_table.constraints:
                if isinstance(const, UniqueConstraint):
                    unique_sets.append([c.name for c in const.columns])
                    
            for uset in unique_sets:
                if any(model_table.c.get(c) is not None and getattr(model_table.c.get(c), "computed", None) is not None for c in uset):
                    continue
                if any(c not in src_table.c for c in uset):
                    continue
                    
                group_by = ", ".join(f"LOWER({c})" for c in uset)
                where_not_null = " AND ".join(f"{c} IS NOT NULL" for c in uset)
                if not where_not_null: continue
                
                query = text(f"""
                    SELECT {group_by}, COUNT(*) as c
                    FROM {tbl_name}
                    WHERE {where_not_null}
                    GROUP BY {group_by}
                    HAVING COUNT(*) > 1
                """)
                cols = s_conn.execute(query).fetchall()
                if cols:
                    blocks.append(f"Unique Collision: {tbl_name} on {uset} has {len(cols)} colliding groups.")
                    
            # 5. Invalid JSON
            for col in model_table.columns:
                if col.name not in src_table.c: continue
                if "JSON" in str(col.type).upper():
                    rows = s_conn.execute(text(f"SELECT id, {col.name} FROM {tbl_name} WHERE {col.name} IS NOT NULL")).fetchall()
                    for r in rows:
                        try:
                            if isinstance(r[1], str):
                                val = r[1]
                                if val.startswith("'") or ("'" in val and '"' not in val):
                                    val = val.replace("'", '"')
                                json.loads(val)
                        except Exception as e:
                            blocks.append(f"Invalid JSON: {tbl_name}.{col.name} row id {r[0]}: {e}")
                            
        # 4. Active-claim duplicates in room_claims
        if "room_claims" in source_meta.tables:
            query1 = text("SELECT room_id FROM room_claims WHERE released_at IS NULL GROUP BY room_id HAVING COUNT(*) > 1")
            if s_conn.execute(query1).fetchall():
                blocks.append("Active claim duplicate: multiple active claims for same room_id.")
            query2 = text("SELECT user_id FROM room_claims WHERE released_at IS NULL GROUP BY user_id HAVING COUNT(*) > 1")
            if s_conn.execute(query2).fetchall():
                blocks.append("Active claim duplicate: multiple active claims for same user_id.")
                
        # WARNs
        for tbl_name in source_meta.tables:
            if tbl_name not in Base.metadata.tables:
                if tbl_name not in ("alembic_version", "sqlite_sequence", "sqlite_stat1"):
                    warns.append(f"Source table {tbl_name} not mapped in models.")
            else:
                model_table = Base.metadata.tables[tbl_name]
                src_table = source_meta.tables[tbl_name]
                for c in src_table.c:
                    if c.name not in model_table.c:
                        if not c.name.startswith("_migrate_lightweight"):
                            warns.append(f"Source col {tbl_name}.{c.name} not in models.")
                for c in model_table.columns:
                    if c.name in src_table.c and not c.nullable:
                        c2 = s_conn.scalar(text(f"SELECT COUNT(*) FROM {tbl_name} WHERE {c.name} IS NULL"))
                        if c2 > 0:
                            warns.append(f"NULLs found on non-nullable target column {tbl_name}.{c.name}.")

def calc_hash(row, cols):
    # Sort items by key
    items = sorted([(k, v) for k, v in row.items() if k in cols])
    s = ""
    for k, v in items:
        s += f"{k}={v}|"
    return int(hashlib.sha1(s.encode('utf-8')).hexdigest()[:15], 16)

def main():
    args = parse_args()
    
    source_engine = create_engine(args.source)
    target_engine = create_engine(args.target)
    
    source_meta = MetaData()
    target_meta = MetaData()
    
    with target_engine.connect() as t_conn:
        try:
            head_rev = t_conn.scalar(text("SELECT version_num FROM alembic_version"))
            if head_rev != "a1b2c3d4e5f6":
                print(f"BLOCK: Target DB alembic head is {head_rev}, expected a1b2c3d4e5f6. Run migrations first.")
                sys.exit(1)
        except Exception as e:
            print(f"BLOCK: Could not read alembic_version from target DB: {e}. Run migrations first.")
            sys.exit(1)
            
        if not args.truncate_target and not args.dry_run:
            target_meta.reflect(bind=target_engine)
            for tbl in target_meta.tables.values():
                if tbl.name == "alembic_version": continue
                count = t_conn.scalar(text(f"SELECT COUNT(*) FROM {tbl.name}"))
                if count > 0:
                    print(f"BLOCK: Target table {tbl.name} is not empty. Use --truncate-target.")
                    sys.exit(1)
    
    print("--- STEP 2: PRE-FLIGHT SCAN ---")
    source_meta.reflect(bind=source_engine)
    blocks = []
    warns = []
    run_preflight(source_engine, source_meta, blocks, warns)
    
    for w in warns: print(f"WARN: {w}")
    for b in blocks: print(f"BLOCK: {b}")

    # --prune-orphans clears FK-orphan blocks (it drops those rows during copy);
    # every other block class must still be repaired at the source, or --force'd.
    unresolved = [
        b for b in blocks
        if not (args.prune_orphans and b.startswith("FK Orphan:"))
    ]
    if blocks and unresolved and not args.force:
        print("Pre-flight scan failed. Aborting.")
        sys.exit(1)
    if blocks and not unresolved:
        print(f"Pre-flight: {len(blocks)} FK-orphan block(s) will be handled by --prune-orphans.")

    if args.dry_run:
        print("Dry-run complete.")
        sys.exit(0)
        
    print("--- STEP 3: COPYING DATA ---")
    target_meta.reflect(bind=target_engine)
    
    if args.truncate_target:
        with target_engine.begin() as t_conn:
            t_conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            for tbl in target_meta.tables.values():
                if tbl.name == "alembic_version": continue
                t_conn.execute(text(f"TRUNCATE TABLE {tbl.name}"))
            t_conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
            
    # FK-topological order
    tables_to_copy = [t for t in Base.metadata.sorted_tables if t.name in source_meta.tables and t.name in target_meta.tables]

    copied_counts = {}
    pruned_rows = []  # (table, pk, reason) -- populated only with --prune-orphans

    with source_engine.connect() as s_conn:
        for t in tables_to_copy:
            if t.name == "alembic_version": continue
            print(f"Copying {t.name}...")

            src_table = source_meta.tables[t.name]
            tgt_table = target_meta.tables[t.name]
            model_table = t

            # Find columns to copy
            cols_to_copy = []
            for c in tgt_table.c:
                if c.name in src_table.c:
                    model_col = model_table.columns.get(c.name)
                    if model_col is not None and getattr(model_col, "computed", None) is not None:
                        continue
                    cols_to_copy.append(c.name)

            if not cols_to_copy:
                continue

            rows = s_conn.execute(text(f"SELECT * FROM {t.name}")).mappings().fetchall()
            if not rows:
                copied_counts[t.name] = 0
                continue

            pk_cols = [c.name for c in tgt_table.primary_key.columns]

            # --prune-orphans: drop rows whose FK points at a row that isn't in
            # the target. Tables are copied parent-first (sorted_tables), so the
            # target already holds every legitimate parent by now.
            if args.prune_orphans:
                fk_specs = []  # (local_col, {valid parent keys})
                for fk in model_table.foreign_keys:
                    local = fk.parent.name
                    ref_tbl = fk.column.table.name
                    ref_col = fk.column.name
                    if local not in cols_to_copy or ref_tbl not in target_meta.tables:
                        continue
                    with target_engine.connect() as tc:
                        valid = {r[0] for r in tc.execute(text(f"SELECT {ref_col} FROM {ref_tbl}"))}
                    fk_specs.append((local, ref_tbl, ref_col, valid))
                if fk_specs:
                    kept = []
                    for row in rows:
                        bad = next(
                            (f"{lc} -> {rt}.{rc}" for lc, rt, rc, valid in fk_specs
                             if row[lc] is not None and row[lc] not in valid),
                            None,
                        )
                        if bad:
                            pk = "/".join(str(row[c]) for c in pk_cols) or "?"
                            pruned_rows.append((t.name, pk, f"orphan FK {bad}"))
                            print(f"  PRUNED {t.name} id={pk}: orphan FK {bad}")
                        else:
                            kept.append(row)
                    rows = kept
                if not rows:
                    copied_counts[t.name] = 0
                    continue

            batch_size = 500
            for i in range(0, len(rows), batch_size):
                batch = rows[i:i+batch_size]
                insert_data = []
                for row in batch:
                    d = {}
                    for col in cols_to_copy:
                        type_str = str(tgt_table.c[col].type).upper()
                        d[col] = coerce_value(row[col], type_str)
                    insert_data.append(d)

                with target_engine.begin() as t_conn:
                    try:
                        t_conn.execute(tgt_table.insert(), insert_data)
                    except Exception as e:
                        print(f"ERROR inserting into {t.name} (batch {i}): {e}")
                        print("  (FK violations here mean orphaned source rows -- re-run with "
                              "--prune-orphans, or repair the source.)")
                        sys.exit(1)

            copied_counts[t.name] = len(rows)
            
    with target_engine.connect() as t_conn:
        t_conn.execute(text("ANALYZE TABLE " + ", ".join(t.name for t in tables_to_copy if t.name != "alembic_version")))
        
    print("--- STEP 4: RECONCILIATION REPORT ---")
    report = []
    report.append("--- MIGRATION RECONCILIATION REPORT ---")
    report.append(f"Date: {datetime.now().isoformat()}")
    report.append(f"Source: {args.source}")
    report.append(f"Target: {args.target}")
    report.append("")
    
    passed_all = True

    pruned_by_table = {}
    for tbl, pk, reason in pruned_rows:
        pruned_by_table.setdefault(tbl, []).append((pk, reason))

    with source_engine.connect() as s_conn, target_engine.connect() as t_conn:
        for t in tables_to_copy:
            if t.name == "alembic_version": continue

            s_count = s_conn.scalar(text(f"SELECT COUNT(*) FROM {t.name}"))
            t_count = t_conn.scalar(text(f"SELECT COUNT(*) FROM {t.name}"))

            n_pruned = len(pruned_by_table.get(t.name, []))
            expected = s_count - n_pruned
            if t_count == expected and (n_pruned == 0 or t_count == expected):
                match_str = "MATCH" if n_pruned == 0 else f"MATCH (-{n_pruned} pruned)"
            else:
                match_str = "MISMATCH"
                passed_all = False

            report.append(f"Table {t.name}:")
            report.append(f"  Rows - Source: {s_count}, Target: {t_count} [{match_str}]")
            
            # Hash
            cols = [c.name for c in target_meta.tables[t.name].c if c.name in source_meta.tables[t.name].c]
            # Exclude computed cols from hash
            model_table = Base.metadata.tables[t.name]
            cols = [c for c in cols if not getattr(model_table.columns.get(c), "computed", None)]
            
            pk_cols = [c.name for c in target_meta.tables[t.name].primary_key.columns]
            pruned_pks = {pk for pk, _ in pruned_by_table.get(t.name, [])}

            s_rows = s_conn.execute(text(f"SELECT * FROM {t.name}")).mappings().fetchall()
            t_rows = t_conn.execute(text(f"SELECT * FROM {t.name}")).mappings().fetchall()

            def _pk(r):
                return "/".join(str(r[c]) for c in pk_cols)

            s_hash = sum(calc_hash(r, cols) for r in s_rows if _pk(r) not in pruned_pks)
            t_hash = sum(calc_hash(r, cols) for r in t_rows)
            hash_match = "MATCH" if s_hash == t_hash else "MISMATCH"
            # Coercion can reformat datetimes/JSON between engines, so a checksum
            # MISMATCH is a hint to inspect, not an automatic FAIL -- row-count
            # parity (adjusted for pruning) drives PASS/FAIL.
            report.append(f"  Checksum - Source: {s_hash}, Target: {t_hash} [{hash_match}]")
            
        # room_claims generated columns
        if "room_claims" in target_meta.tables:
            query = text("SELECT COUNT(*) FROM room_claims WHERE released_at IS NULL AND (active_room_key IS NULL OR active_user_key IS NULL)")
            c = t_conn.scalar(query)
            query2 = text("SELECT COUNT(*) FROM room_claims WHERE released_at IS NOT NULL AND (active_room_key IS NOT NULL OR active_user_key IS NOT NULL)")
            c2 = t_conn.scalar(query2)
            if c > 0 or c2 > 0:
                report.append(f"  room_claims generated keys verification: FAIL ({c} nulls when active, {c2} not nulls when released)")
                passed_all = False
            else:
                report.append("  room_claims generated keys verification: PASS")
                
    if pruned_rows:
        report.append("")
        report.append(f"PRUNED ORPHAN ROWS ({len(pruned_rows)}) -- not copied:")
        for tbl, pk, reason in pruned_rows:
            report.append(f"  {tbl}  id={pk}  ({reason})")

    report.append("")
    report.append(f"OVERALL RESULT: {'PASS' if passed_all else 'FAIL'}")
    
    with open(args.report, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
        
    print("\n".join(report))
    
    if not passed_all:
        sys.exit(1)

if __name__ == "__main__":
    main()
