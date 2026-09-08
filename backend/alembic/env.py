import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Ensure backend root is on sys.path so app modules can be imported
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import Base, SQLALCHEMY_DATABASE_URL
import app.models  # noqa: F401 - side-effect import: registers every model on Base.metadata for autogenerate

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Resolve Database URL: DATABASE_URL env var -> database.py SQLALCHEMY_DATABASE_URL default
db_url = os.environ.get("DATABASE_URL", SQLALCHEMY_DATABASE_URL)
config.set_main_option("sqlalchemy.url", db_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
#
# disable_existing_loggers=False (P1.10 fix): fileConfig's DEFAULT is True,
# which silently sets `.disabled = True` on every logger object that
# already exists in logging.Logger.manager.loggerDict at this point and
# isn't one of the handful alembic.ini itself declares (root/sqlalchemy/
# alembic) -- permanently, for the rest of the process, with no error or
# warning. On SQLite, _ensure_schema() (app/main.py) runs this exact
# upgrade at EVERY app import, and app.main's own import chain has already
# created most app.* module loggers (logging.getLogger(__name__)) by the
# time it gets here -- so without this flag, every one of them goes
# permanently silent right after boot, discovered via app/ldap_auth.py's
# warning logs (directory errors, unmapped groups, wrong passwords) never
# appearing anywhere, including in this project's own test suite via
# pytest's caplog. Loggers created AFTER this point (e.g. main.py's
# `clarion.cors`, declared further down) were unaffected, which is what
# made this easy to miss.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# target_metadata for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        # batch mode is a SQLite necessity (no ALTER for most ops); on MariaDB
        # it can turn an alter_column/drop_column into an unwanted table copy.
        render_as_batch=url.startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
