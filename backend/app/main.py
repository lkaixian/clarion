from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from . import models
from .database import engine
from .routers import auth_router, patients, emergency, ai_router

models.Base.metadata.create_all(bind=engine)


def _migrate_lightweight():
    """This project has no Alembic (SQLite + `create_all`, hackathon-scale
    on purpose) — `create_all` only creates *missing tables*, not missing
    *columns* on tables that already existed on disk. So when a column is
    added to an existing model (like `EmergencyToken.nfc_uid`), an
    already-seeded `medibridge.db` from before that change needs a manual
    `ALTER TABLE`. This runs once at startup, is a no-op if the column
    already exists, and only ever adds columns — never destructive."""
    inspector = inspect(engine)
    if "emergency_tokens" not in inspector.get_table_names():
        return
    existing_columns = {col["name"] for col in inspector.get_columns("emergency_tokens")}
    with engine.begin() as conn:
        if "nfc_uid" not in existing_columns:
            conn.execute(text("ALTER TABLE emergency_tokens ADD COLUMN nfc_uid VARCHAR"))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_emergency_tokens_nfc_uid "
                "ON emergency_tokens (nfc_uid)"
            ))
        if "registered_by" not in existing_columns:
            conn.execute(text("ALTER TABLE emergency_tokens ADD COLUMN registered_by VARCHAR"))


_migrate_lightweight()

app = FastAPI(
    title="MediBridge API",
    description="Emergency-first, interoperable health record continuity system.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your web/mobile origins before any real deployment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(patients.router)
app.include_router(emergency.router)
app.include_router(ai_router.router)


@app.get("/")
def root():
    return {"status": "MediBridge API running", "docs": "/docs"}
