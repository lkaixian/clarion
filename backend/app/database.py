import os
from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./clarion.db")

if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
    )
else:
    # MariaDB/MySQL (P1.3). 4 workers x (pool_size + max_overflow) = 4 x 40 = 160
    # < MariaDB max_connections=200, leaving headroom for clarion_migrate /
    # clarion_report / exporters / root. pool_timeout is short so a connection
    # squeeze fails fast (500) instead of hanging the request for 30s.
    # READ COMMITTED: web-request default -- avoids InnoDB REPEATABLE READ gap
    # locks on the queue-number and RoomClaim unique-insert retry loops, and
    # stops a long-lived read-only request from pinning a stale MVCC snapshot.
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_size=10,
        max_overflow=30,
        pool_timeout=10,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_use_lifo=True,
        isolation_level="READ COMMITTED",
        connect_args={"charset": "utf8mb4"},
    )
DB_BACKEND = engine.url.get_backend_name()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# SQLAlchemy MetaData naming conventions for deterministic, portable constraint names across SQLite/MariaDB
naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=naming_convention)
Base = declarative_base(metadata=metadata)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
