"""Schema-integrity gate for CI (roadmap P1.5; wired into the pipeline at P2.11).

Runs three assertions against a THROWAWAY database given by --url (default: a
fresh temp SQLite file). Exits non-zero on the first failure.

  1. `alembic upgrade head` succeeds from an empty database.
  2. autogenerate against head produces an EMPTY migration -- i.e. models.py and
     the migration chain fully agree (Security Audit M9, the tender).
  3. `upgrade head -> downgrade base -> upgrade head` round-trips cleanly (every
     migration is reversible).

Usage:
  python -m db.check_schema
  python -m db.check_schema --url "mysql+pymysql://clarion_migrate:PW@host:3306/clarion_citest?charset=utf8mb4"
"""
import argparse
import os
import sys
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

BACKEND = Path(__file__).resolve().parent.parent
INI = BACKEND / "alembic.ini"


def _cfg(url: str) -> Config:
    os.environ["DATABASE_URL"] = url  # alembic/env.py reads this
    return Config(str(INI))


def _fail(msg: str) -> "None":
    print(f"FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None, help="throwaway DB URL (default: temp SQLite)")
    args = ap.parse_args()

    tmp = None
    url = args.url
    if url is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        url = f"sqlite:///{tmp.name}"

    cfg = _cfg(url)
    head = ScriptDirectory.from_config(cfg).get_current_head()
    print(f"target head: {head}   url: {url.split('@')[-1]}")

    try:
        # 1. upgrade head
        command.upgrade(cfg, "head")
        eng = create_engine(url)
        with eng.connect() as c:
            cur = MigrationContext.configure(c).get_current_revision()
        eng.dispose()
        if cur != head:
            _fail(f"after upgrade head, revision is {cur!r}, expected {head!r}")
        print("  [1/3] upgrade head OK")

        # 2. autogenerate must be empty
        tempfile.mkdtemp()
        cfg.set_main_option("version_locations", str(BACKEND / "alembic" / "versions"))
        script = command.revision(cfg, message="_ci_autogen_probe", autogenerate=True)
        probe = Path(script.path)
        body = probe.read_text(encoding="utf-8")
        probe.unlink()
        # crude but effective: an empty autogen migration has only `pass` in upgrade()
        upgrade_body = body.split("def upgrade()")[1].split("def downgrade()")[0]
        if any(tok in upgrade_body for tok in ("op.add_", "op.drop_", "op.alter_", "op.create_", "op.execute")):
            _fail("autogenerate against head is NOT empty -- models.py has drifted from the "
                  f"migration chain:\n{upgrade_body}")
        print("  [2/3] autogenerate against head is empty OK")

        # 3. reversibility
        command.downgrade(cfg, "base")
        eng = create_engine(url)
        with eng.connect() as c:
            cur = MigrationContext.configure(c).get_current_revision()
        eng.dispose()
        if cur is not None:
            _fail(f"after downgrade base, revision is {cur!r}, expected None")
        command.upgrade(cfg, "head")
        print("  [3/3] downgrade base -> upgrade head round-trip OK")

    finally:
        if tmp is not None:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass  # Windows may still hold the handle briefly; it's a temp file

    print("PASS")


if __name__ == "__main__":
    main()
