"""Online booking v2: patient app books a slot at a hospital that has turned
online booking on, against a timetable the hospital's own admin controls.

Slots are NEVER stored: they are computed on read from booking_services +
booking_hours in the facility's own timezone (hospital_settings.timezone) and
always serialised with an explicit UTC offset (the Dart client mis-parses a
naive datetime). Capacity is counted from `scheduled` appointments with the
same facility + booking_category + scheduled_at, so there is no second
source of truth to drift.

The older department/clinician self-book in routers/appointments.py is
untouched; this router only reuses its serialiser and UTC helper.
"""
import math
from datetime import date as date_cls, datetime, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from jose import JWTError, jwt
from slowapi.util import get_remote_address
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..appointments import MALAYSIA_TZ
from ..audit import log_access
from ..database import get_db
from ..rate_limit import limiter
from .appointments import _serialize_appointment, _to_aware_utc

router = APIRouter(prefix="/booking", tags=["booking"])

CATEGORIES = {
    "general": "General consultation",
    "chronic": "Follow-up and chronic care",
    "vaccination": "Vaccination",
    "maternal_child": "Maternal and child health",
    "dental": "Dental",
    "screening": "Health screening",
    "mental_health": "Mental health and counselling",
    "physio": "Physiotherapy and rehabilitation",
}
MAX_PROFILES_PER_USER = 10
_DEFAULTS = {"slot_minutes": 30, "capacity": 1, "advance_days": 14, "min_notice_minutes": 60}


# ---------------------------------------------------------------------------
# Slot engine
# ---------------------------------------------------------------------------

def _tz(setting: models.HospitalSetting) -> ZoneInfo:
    try:
        return ZoneInfo(setting.timezone or "Asia/Kuala_Lumpur")
    except Exception:  # unknown/garbled tz name in settings: fall back, never 500
        return MALAYSIA_TZ


def _require_category(category: str) -> str:
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Unknown category '{category}'")
    return category


def _enabled_setting(db: Session, facility_name: str) -> models.HospitalSetting:
    s = (
        db.query(models.HospitalSetting)
        .filter(models.HospitalSetting.facility_name == facility_name,
                models.HospitalSetting.online_booking_enabled.is_(True))
        .first()
    )
    if not s:  # disabled and unknown look identical on purpose
        raise HTTPException(status_code=404, detail="Online booking is not available at this facility")
    return s


def _active_service(db: Session, facility_name: str, category: str) -> models.BookingService:
    svc = (
        db.query(models.BookingService)
        .filter(models.BookingService.facility_name == facility_name,
                models.BookingService.category == category,
                models.BookingService.active.is_(True))
        .first()
    )
    if not svc:
        raise HTTPException(status_code=404, detail="This facility does not offer that service online")
    return svc


def _slots(db: Session, tz: ZoneInfo, svc: models.BookingService, first_date: date_cls, ndays: int):
    """[(start_local, end_local, remaining)] sorted by start, for `ndays`
    local dates from first_date, already filtered by min_notice and
    advance_days. Full slots are included with remaining 0."""
    hours = db.query(models.BookingHour).filter(models.BookingHour.service_id == svc.id).all()
    by_wd: dict[int, list] = {}
    for h in hours:
        by_wd.setdefault(h.weekday, []).append(h)
    now = datetime.now(timezone.utc)
    earliest = now + timedelta(minutes=svc.min_notice_minutes)
    latest = now + timedelta(days=svc.advance_days)

    out = []
    for i in range(ndays):
        d = first_date + timedelta(days=i)
        midnight = datetime(d.year, d.month, d.day, tzinfo=tz)
        for h in by_wd.get(d.weekday(), []):
            m = h.start_minute
            while m + svc.slot_minutes <= h.end_minute:
                start = midnight + timedelta(minutes=m)  # wall-clock arithmetic
                su = start.astimezone(timezone.utc)
                if earliest <= su <= latest:
                    out.append((start, start + timedelta(minutes=svc.slot_minutes), su))
                m += svc.slot_minutes
    if not out:
        return []
    out.sort(key=lambda t: t[2])
    lo, hi = out[0][2], out[-1][2]
    booked: dict[datetime, int] = {}
    rows = (
        db.query(models.Appointment.scheduled_at)
        .filter(models.Appointment.facility_name == svc.facility_name,
                models.Appointment.booking_category == svc.category,
                models.Appointment.status == "scheduled",
                models.Appointment.scheduled_at >= lo,
                models.Appointment.scheduled_at <= hi)
        .all()
    )
    for (at,) in rows:
        k = _to_aware_utc(at)
        booked[k] = booked.get(k, 0) + 1
    return [(s, e, max(0, svc.capacity - booked.get(su, 0))) for s, e, su in out]


def _count_booked(db: Session, facility_name: str, category: str, at_utc: datetime) -> int:
    return (
        db.query(models.Appointment)
        .filter(models.Appointment.facility_name == facility_name,
                models.Appointment.booking_category == category,
                models.Appointment.status == "scheduled",
                models.Appointment.scheduled_at == at_utc)
        .count()
    )


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Patient-facing
# ---------------------------------------------------------------------------

@router.get("/categories")
def list_categories(_: models.User = Depends(auth.get_current_user)):
    return [{"code": c, "label": l} for c, l in CATEGORIES.items()]


@router.get("/facilities")
def list_facilities(
    category: str,
    q: Optional[str] = Query(default=None, max_length=100),
    lat: Optional[float] = Query(default=None, ge=-90, le=90),
    lng: Optional[float] = Query(default=None, ge=-180, le=180),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    _require_category(category)
    if (lat is None) != (lng is None):
        raise HTTPException(status_code=422, detail="lat and lng must be given together")

    rows = (
        db.query(models.HospitalSetting, models.BookingService)
        .join(models.BookingService, models.BookingService.facility_name == models.HospitalSetting.facility_name)
        .filter(models.HospitalSetting.online_booking_enabled.is_(True),
                models.BookingService.category == category,
                models.BookingService.active.is_(True))
        .all()
    )
    words = [w for w in (q or "").lower().split() if w]
    items = []
    for s, svc in rows:
        display = s.display_name or s.facility_name
        hay = " ".join(x for x in (display, s.address, s.facility_name) if x).lower()
        if any(w not in hay for w in words):
            continue
        dist = None
        if lat is not None and s.latitude is not None and s.longitude is not None:
            dist = round(_haversine_km(lat, lng, s.latitude, s.longitude), 2)
        items.append((s, svc, display, dist))

    if lat is not None:
        items.sort(key=lambda t: (t[3] is None, t[3] or 0.0, t[2].lower()))
    else:
        items.sort(key=lambda t: t[2].lower())

    out = []
    for s, svc, display, dist in items[:limit]:  # next_available is computed only for what is returned
        tz = _tz(s)
        today = datetime.now(tz).date()
        nxt = next((st for st, _e, rem in _slots(db, tz, svc, today, svc.advance_days + 1) if rem > 0), None)
        out.append({
            "facility_name": s.facility_name,
            "display_name": display,
            "address": s.address,
            "contact_phone": s.contact_phone,
            "latitude": s.latitude,
            "longitude": s.longitude,
            "distance_km": dist,
            "next_available_at": nxt.isoformat() if nxt else None,
        })
    return out


@router.get("/facilities/{facility_name}/availability")
def facility_availability(
    facility_name: str,
    category: str,
    days: int = Query(default=14, ge=1, le=90),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    _require_category(category)
    s = _enabled_setting(db, facility_name)
    svc = _active_service(db, facility_name, category)
    tz = _tz(s)
    days = min(days, svc.advance_days)
    today = datetime.now(tz).date()
    counts = {today + timedelta(days=i): 0 for i in range(days)}
    for start, _e, rem in _slots(db, tz, svc, today, days):
        if rem > 0 and start.date() in counts:
            counts[start.date()] += 1
    return {
        "facility_name": facility_name,
        "category": category,
        "slot_minutes": svc.slot_minutes,
        "capacity": svc.capacity,
        "days": [{"date": d.isoformat(), "open_slots": n} for d, n in counts.items()],
    }


@router.get("/facilities/{facility_name}/slots")
def facility_slots(
    facility_name: str,
    category: str,
    date: date_cls,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_user),
):
    _require_category(category)
    s = _enabled_setting(db, facility_name)
    svc = _active_service(db, facility_name, category)
    tz = _tz(s)
    return {
        "date": date.isoformat(),
        "slot_minutes": svc.slot_minutes,
        "slots": [
            {"start": st.isoformat(), "end": en.isoformat(), "remaining": rem}
            for st, en, rem in _slots(db, tz, svc, date, 1)
        ],
    }


def _book_user_key(request: Request) -> str:
    """Rate-limit key = the verified token's user id. Resolved from the header
    (not from a dependency) because the global rate-limit dependency runs
    before any route dependency. An unverifiable token falls back to the IP."""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token:
        try:
            sub = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM]).get("sub")
            if sub:
                return f"booking:{sub}"
        except JWTError:
            pass
    return get_remote_address(request)


@router.post("/appointments", response_model=schemas.BookingAppointmentOut)
@limiter.limit("20/minute", key_func=_book_user_key)  # per user, on top of the global per-IP default
def book_appointment(
    request: Request,
    payload: schemas.BookingAppointmentCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    if user.role != "patient" or not user.patient_id:
        raise HTTPException(
            status_code=403,
            detail="Online booking needs a patient account linked to a patient record. Register at the clinic first.",
        )
    _require_category(payload.category)
    if payload.scheduled_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="scheduled_at must include a UTC offset, e.g. +08:00")

    s = _enabled_setting(db, payload.facility_name)
    svc = _active_service(db, payload.facility_name, payload.category)
    tz = _tz(s)

    profile = None
    if payload.profile_id:
        profile = (
            db.query(models.BookingProfile)
            .filter(models.BookingProfile.id == payload.profile_id,
                    models.BookingProfile.owner_user_id == user.id)
            .first()
        )
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")

    requested = _to_aware_utc(payload.scheduled_at)
    local_date = requested.astimezone(tz).date()
    match = next(
        (rem for st, _e, rem in _slots(db, tz, svc, local_date, 1) if st.astimezone(timezone.utc) == requested),
        None,
    )
    if match is None or match <= 0:
        raise HTTPException(status_code=409, detail="That slot is no longer available. Please pick another.")

    appt = models.Appointment(
        patient_id=user.patient_id,
        facility_name=payload.facility_name,
        scheduled_at=requested,
        reason=payload.reason or CATEGORIES[payload.category],
        status="scheduled",
        created_by=user.id,
        self_booked=True,
        booking_category=payload.category,
        department=None,
        clinician_id=None,
    )
    if profile:
        appt.booked_for_profile_id = profile.id
        appt.attendee_name = profile.full_name
        appt.attendee_relationship = profile.relationship
        appt.attendee_dob = profile.date_of_birth
    db.add(appt)
    try:
        db.flush()
        # Re-count inside the same transaction: a concurrent booking that
        # slipped past the check above makes this exceed capacity.
        if _count_booked(db, payload.facility_name, payload.category, requested) > svc.capacity:
            db.rollback()
            raise HTTPException(status_code=409, detail="That slot is no longer available. Please pick another.")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="That slot is no longer available. Please pick another.")
    db.refresh(appt)

    log_access(
        db, user.patient_id, user.id, user.role, "online_book_appointment",
        detail=f"facility={payload.facility_name} category={payload.category} appointment={appt.id}",
    )
    out = _serialize_appointment(appt, db)
    out["facility_display_name"] = out["display_name"] = s.display_name or s.facility_name
    return out


@router.post("/appointments/{appointment_id}/cancel", response_model=schemas.AppointmentOut)
def cancel_booking(
    appointment_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    appt = (
        db.query(models.Appointment)
        .filter(models.Appointment.id == appointment_id,
                models.Appointment.created_by == user.id,
                models.Appointment.booking_category.isnot(None))
        .first()
    )
    if not appt:  # someone else's, or not an online booking: indistinguishable
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status != "scheduled":
        raise HTTPException(status_code=409, detail=f"Appointment is already {appt.status}")
    if _to_aware_utc(appt.scheduled_at) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="A past appointment cannot be cancelled")
    appt.status = "cancelled"
    db.commit()
    db.refresh(appt)
    log_access(
        db, appt.patient_id, user.id, user.role, "online_cancel_appointment",
        detail=f"facility={appt.facility_name} appointment={appt.id}",
    )
    return _serialize_appointment(appt, db)


# ---------------------------------------------------------------------------
# Saved profiles (owner only; anyone else's id is a 404)
# ---------------------------------------------------------------------------

def _own_profile(db: Session, user: models.User, profile_id: str) -> models.BookingProfile:
    p = (
        db.query(models.BookingProfile)
        .filter(models.BookingProfile.id == profile_id, models.BookingProfile.owner_user_id == user.id)
        .first()
    )
    if not p:
        raise HTTPException(status_code=404, detail="Profile not found")
    return p


@router.get("/profiles", response_model=List[schemas.BookingProfileOut])
def list_profiles(db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_user)):
    return (
        db.query(models.BookingProfile)
        .filter(models.BookingProfile.owner_user_id == user.id)
        .order_by(models.BookingProfile.created_at.asc(), models.BookingProfile.id.asc())
        .all()
    )


@router.post("/profiles", response_model=schemas.BookingProfileOut, status_code=201)
def create_profile(
    payload: schemas.BookingProfileIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    n = db.query(models.BookingProfile).filter(models.BookingProfile.owner_user_id == user.id).count()
    if n >= MAX_PROFILES_PER_USER:
        raise HTTPException(status_code=409, detail=f"You can save up to {MAX_PROFILES_PER_USER} people")
    p = models.BookingProfile(owner_user_id=user.id, **payload.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    log_access(db, user.patient_id, user.id, user.role, "booking_profile_create", detail=f"profile={p.id}")
    return p


@router.patch("/profiles/{profile_id}", response_model=schemas.BookingProfileOut)
def update_profile(
    profile_id: str,
    payload: schemas.BookingProfilePatch,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    p = _own_profile(db, user, profile_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is None and k in ("full_name", "relationship"):
            continue  # NOT NULL columns: null means "leave as is"
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    log_access(db, user.patient_id, user.id, user.role, "booking_profile_update", detail=f"profile={p.id}")
    return p


@router.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(
    profile_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    p = _own_profile(db, user, profile_id)
    # The snapshot on the appointment survives; only the link goes. Done here
    # as well as by ON DELETE SET NULL because SQLite runs without FK enforcement.
    db.query(models.Appointment).filter(models.Appointment.booked_for_profile_id == p.id).update(
        {models.Appointment.booked_for_profile_id: None}, synchronize_session=False
    )
    db.delete(p)
    db.commit()
    log_access(db, user.patient_id, user.id, user.role, "booking_profile_delete", detail=f"profile={profile_id}")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Hospital admin: own facility only, taken from the token, never the request
# ---------------------------------------------------------------------------

def _admin_facility(user: models.User) -> str:
    if not user.facility:
        raise HTTPException(status_code=403, detail="Your account is not attached to a facility")
    return user.facility


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _parse_hhmm(text: str, what: str) -> int:
    h, m = int(text[:2]), int(text[3:])
    if m > 59 or h > 24 or (h == 24 and m != 0):
        raise HTTPException(status_code=422, detail=f"{what} '{text}' is not a valid time (00:00 to 24:00)")
    return h * 60 + m


def _admin_view(db: Session, facility: str) -> dict:
    s = db.query(models.HospitalSetting).filter(models.HospitalSetting.facility_name == facility).first()
    svcs = {
        v.category: v
        for v in db.query(models.BookingService).filter(models.BookingService.facility_name == facility).all()
    }
    hours: dict[str, list] = {}
    if svcs:
        ids = {v.id: c for c, v in svcs.items()}
        for h in (
            db.query(models.BookingHour)
            .filter(models.BookingHour.service_id.in_(list(ids)))
            .order_by(models.BookingHour.weekday, models.BookingHour.start_minute)
            .all()
        ):
            hours.setdefault(ids[h.service_id], []).append(
                {"weekday": h.weekday, "start": _hhmm(h.start_minute), "end": _hhmm(h.end_minute)}
            )
    services = []
    for code, label in CATEGORIES.items():
        v = svcs.get(code)
        services.append({
            "category": code,
            "label": label,
            "active": bool(v.active) if v else False,
            "slot_minutes": v.slot_minutes if v else _DEFAULTS["slot_minutes"],
            "capacity": v.capacity if v else _DEFAULTS["capacity"],
            "advance_days": v.advance_days if v else _DEFAULTS["advance_days"],
            "min_notice_minutes": v.min_notice_minutes if v else _DEFAULTS["min_notice_minutes"],
            "hours": hours.get(code, []),
        })
    return {
        "facility_name": facility,
        "display_name": (s.display_name if s and s.display_name else facility),
        "address": s.address if s else None,
        "online_booking_enabled": bool(s.online_booking_enabled) if s else False,
        "latitude": s.latitude if s else None,
        "longitude": s.longitude if s else None,
        "services": services,
    }


@router.get("/admin/settings")
def get_admin_settings(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("admin")),
):
    return _admin_view(db, _admin_facility(user))


@router.put("/admin/settings")
def put_admin_settings(
    payload: schemas.BookingAdminSettingsIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("admin")),
):
    facility = _admin_facility(user)

    if (payload.latitude is None) != (payload.longitude is None):
        raise HTTPException(status_code=422, detail="latitude and longitude must be set together")
    if payload.latitude is not None and not -90 <= payload.latitude <= 90:
        raise HTTPException(status_code=422, detail="latitude must be between -90 and 90")
    if payload.longitude is not None and not -180 <= payload.longitude <= 180:
        raise HTTPException(status_code=422, detail="longitude must be between -180 and 180")

    # Validate everything before touching the DB so a bad body changes nothing.
    seen = set()
    parsed = []  # (service, [(weekday, start, end)])
    for svc in payload.services:
        if svc.category not in CATEGORIES:
            raise HTTPException(status_code=422, detail=f"Unknown category '{svc.category}'")
        if svc.category in seen:
            raise HTTPException(status_code=422, detail=f"Category '{svc.category}' appears twice")
        seen.add(svc.category)
        label = CATEGORIES[svc.category]
        rngs = []
        for h in svc.hours:
            a, b = _parse_hhmm(h.start, "start"), _parse_hhmm(h.end, "end")
            if a >= 1440 or b <= a:
                raise HTTPException(status_code=422, detail=f"{label}: end must be after start ({h.start}-{h.end})")
            if b - a < svc.slot_minutes:
                raise HTTPException(
                    status_code=422,
                    detail=f"{label}: {h.start}-{h.end} is shorter than one {svc.slot_minutes}-minute slot",
                )
            rngs.append((h.weekday, a, b))
        rngs.sort()
        for prev, cur in zip(rngs, rngs[1:]):
            if prev[0] == cur[0] and cur[1] < prev[2]:
                raise HTTPException(
                    status_code=422,
                    detail=f"{label}: opening ranges overlap on weekday {cur[0]} "
                           f"({_hhmm(prev[1])}-{_hhmm(prev[2])} and {_hhmm(cur[1])}-{_hhmm(cur[2])})",
                )
        parsed.append((svc, rngs))

    s = db.query(models.HospitalSetting).filter(models.HospitalSetting.facility_name == facility).first()
    if not s:
        s = models.HospitalSetting(facility_name=facility)
        db.add(s)
    s.online_booking_enabled = payload.online_booking_enabled
    s.latitude = payload.latitude
    s.longitude = payload.longitude
    s.updated_by = user.id

    existing = {
        v.category: v
        for v in db.query(models.BookingService).filter(models.BookingService.facility_name == facility).all()
    }
    if existing:  # explicit: SQLite does not cascade
        db.query(models.BookingHour).filter(
            models.BookingHour.service_id.in_([v.id for v in existing.values()])
        ).delete(synchronize_session=False)
    for code, v in existing.items():
        if code not in seen:
            db.delete(v)
    db.flush()
    for svc, rngs in parsed:
        row = existing.get(svc.category)
        if row is None:
            row = models.BookingService(facility_name=facility, category=svc.category)
            db.add(row)
        row.active = svc.active
        row.slot_minutes = svc.slot_minutes
        row.capacity = svc.capacity
        row.advance_days = svc.advance_days
        row.min_notice_minutes = svc.min_notice_minutes
        db.flush()
        for wd, a, b in rngs:
            db.add(models.BookingHour(service_id=row.id, weekday=wd, start_minute=a, end_minute=b))
    db.commit()

    log_access(
        db, None, user.id, user.role, "update_booking_settings",
        detail=f"enabled={payload.online_booking_enabled} services={len(parsed)}",
        actor_facility=user.facility,
    )
    return _admin_view(db, facility)
