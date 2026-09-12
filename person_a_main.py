"""
main.py
Person A's FastAPI app. Every endpoint here matches something the frontend
(rural-hospital-resource-network.html) already calls — nothing here should
require a frontend change.

Run: uvicorn main:app --reload --port 8000
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from person_a_database import db_session, init_db
from person_a_auth import hash_password, verify_password, generate_session_token
from person_b_matching import rank_resource_matches, rank_referral_matches

app = FastAPI(title="Rural Hospital Resource Network")

# Credits awarded to a hospital for fulfilling a request/referral, scaled by
# urgency — this is the gamification layer the judges asked for after round 1.
URGENCY_CREDIT = {"critical": 20, "high": 12, "medium": 7, "low": 3}

# Hackathon CORS: frontend may be opened as a local file or served from a
# different port than the API, so allow everything rather than burning
# demo time debugging a CORS error on stage.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


# ---------------------------------------------------------------------------
# Pydantic request bodies (mirrors exactly what the frontend sends)
# ---------------------------------------------------------------------------

class RegisterBody(BaseModel):
    name: str
    lat: float
    lng: float
    contact_phone: Optional[str] = None
    password: str


class LoginBody(BaseModel):
    name: str
    password: str


class ResourceBody(BaseModel):
    hospital_id: int
    resource_type: str
    quantity: int
    unit: Optional[str] = None


class CapabilityBody(BaseModel):
    hospital_id: int
    facility_type: str
    available_capacity: int


class RequestBody(BaseModel):
    requesting_hospital_id: int
    resource_type: str
    quantity_needed: int
    urgency: str


class ReferralBody(BaseModel):
    patient_id: Optional[str] = None
    patient_name: str
    referring_hospital_id: int
    required_facility: str
    reason: Optional[str] = None
    urgency: str
    preferred_radius_km: Optional[float] = None
    notes: Optional[str] = None


class AcceptRequestBody(BaseModel):
    request_id: int
    fulfilling_hospital_id: int


class AcceptReferralBody(BaseModel):
    referral_id: int
    accepting_hospital_id: int


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.post("/hospitals/register")
def register(body: RegisterBody):
    password_hash, salt = hash_password(body.password)
    with db_session() as db:
        existing = db.execute("SELECT id FROM hospitals WHERE name = ?", (body.name,)).fetchone()
        if existing:
            raise HTTPException(400, "A hospital with that name is already registered.")
        db.execute(
            """INSERT INTO hospitals (name, lat, lng, contact_phone, password_hash, salt)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (body.name, body.lat, body.lng, body.contact_phone, password_hash, salt),
        )
    return {"status": "registered"}


@app.post("/auth/login")
def login(body: LoginBody):
    with db_session() as db:
        row = db.execute("SELECT * FROM hospitals WHERE name = ?", (body.name,)).fetchone()
        if not row or not verify_password(body.password, row["password_hash"], row["salt"]):
            raise HTTPException(401, "Invalid hospital name or password.")
        token = generate_session_token()
        db.execute("INSERT INTO sessions (token, hospital_id) VALUES (?, ?)", (token, row["id"]))
    # `token` is returned for whenever the frontend is upgraded to send it
    # back as a Bearer header (see the NOTE in auth.py) — harmless to include
    # now even though the current frontend ignores it.
    return {"hospital_id": row["id"], "token": token}


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@app.get("/resources")
def list_resources(hospital_id: int):
    with db_session() as db:
        rows = db.execute(
            "SELECT resource_type, quantity, unit FROM resources WHERE hospital_id = ?",
            (hospital_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/resources")
def upsert_resource(body: ResourceBody):
    with db_session() as db:
        db.execute(
            """INSERT INTO resources (hospital_id, resource_type, quantity, unit)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(hospital_id, resource_type)
               DO UPDATE SET quantity = excluded.quantity, unit = excluded.unit""",
            (body.hospital_id, body.resource_type, body.quantity, body.unit),
        )
    return {"status": "saved"}


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------

@app.get("/capabilities")
def list_capabilities(hospital_id: int):
    with db_session() as db:
        rows = db.execute(
            "SELECT facility_type, available_capacity FROM capabilities WHERE hospital_id = ?",
            (hospital_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/capabilities")
def upsert_capability(body: CapabilityBody):
    with db_session() as db:
        db.execute(
            """INSERT INTO capabilities (hospital_id, facility_type, available_capacity)
               VALUES (?, ?, ?)
               ON CONFLICT(hospital_id, facility_type)
               DO UPDATE SET available_capacity = excluded.available_capacity""",
            (body.hospital_id, body.facility_type, body.available_capacity),
        )
    return {"status": "saved"}


# ---------------------------------------------------------------------------
# Resource requests
# ---------------------------------------------------------------------------

@app.post("/requests")
def create_request(body: RequestBody):
    with db_session() as db:
        cur = db.execute(
            """INSERT INTO requests (requesting_hospital_id, resource_type, quantity_needed, urgency)
               VALUES (?, ?, ?, ?)""",
            (body.requesting_hospital_id, body.resource_type, body.quantity_needed, body.urgency),
        )
    return {"request_id": cur.lastrowid}


@app.get("/requests")
def list_requests(hospital_id: int):
    with db_session() as db:
        rows = db.execute(
            """SELECT resource_type, quantity_needed, urgency, status
               FROM requests WHERE requesting_hospital_id = ? ORDER BY created_at DESC""",
            (hospital_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/requests/{request_id}/matches")
def get_request_matches(request_id: int):
    with db_session() as db:
        req = db.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
        if not req:
            raise HTTPException(404, "Request not found.")
        requester = db.execute(
            "SELECT lat, lng FROM hospitals WHERE id = ?", (req["requesting_hospital_id"],)
        ).fetchone()

        candidates = db.execute(
            """SELECT h.id AS hospital_id, h.name, h.lat, h.lng, r.quantity AS quantity_available
               FROM resources r JOIN hospitals h ON h.id = r.hospital_id
               WHERE r.resource_type = ? AND r.quantity > 0 AND h.id != ?""",
            (req["resource_type"], req["requesting_hospital_id"]),
        ).fetchall()

    ranked = rank_resource_matches(
        request={
            "lat": requester["lat"],
            "lng": requester["lng"],
            "urgency": req["urgency"],
            "quantity_needed": req["quantity_needed"],
        },
        candidates=[dict(c) for c in candidates],
    )
    return ranked


@app.post("/requests/accept")
def accept_request(body: AcceptRequestBody):
    with db_session() as db:
        req = db.execute("SELECT * FROM requests WHERE id = ?", (body.request_id,)).fetchone()
        if not req:
            raise HTTPException(404, "Request not found.")
        db.execute(
            "UPDATE requests SET status = 'fulfilled', fulfilling_hospital_id = ? WHERE id = ?",
            (body.fulfilling_hospital_id, body.request_id),
        )
        # Deduct what was given, and credit the fulfilling hospital — this is
        # the gamification hook the judges asked for after round 1.
        db.execute(
            "UPDATE resources SET quantity = MAX(quantity - ?, 0) WHERE hospital_id = ? AND resource_type = ?",
            (req["quantity_needed"], body.fulfilling_hospital_id, req["resource_type"]),
        )
        db.execute(
            "UPDATE hospitals SET credit_balance = credit_balance + ? WHERE id = ?",
            (URGENCY_CREDIT.get(req["urgency"], 5), body.fulfilling_hospital_id),
        )
    return {"status": "accepted"}


# ---------------------------------------------------------------------------
# Patient referrals
# ---------------------------------------------------------------------------

@app.post("/referrals")
def create_referral(body: ReferralBody):
    with db_session() as db:
        cur = db.execute(
            """INSERT INTO referrals
               (patient_id, patient_name, referring_hospital_id, required_facility,
                reason, urgency, preferred_radius_km, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (body.patient_id, body.patient_name, body.referring_hospital_id, body.required_facility,
             body.reason, body.urgency, body.preferred_radius_km, body.notes),
        )
    return {"referral_id": cur.lastrowid}


@app.get("/referrals")
def list_referrals(hospital_id: int):
    with db_session() as db:
        rows = db.execute(
            """SELECT patient_name, required_facility, urgency, status
               FROM referrals WHERE referring_hospital_id = ? ORDER BY created_at DESC""",
            (hospital_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/referrals/{referral_id}/matches")
def get_referral_matches(referral_id: int):
    with db_session() as db:
        ref = db.execute("SELECT * FROM referrals WHERE id = ?", (referral_id,)).fetchone()
        if not ref:
            raise HTTPException(404, "Referral not found.")
        referrer = db.execute(
            "SELECT lat, lng FROM hospitals WHERE id = ?", (ref["referring_hospital_id"],)
        ).fetchone()

        candidates = db.execute(
            """SELECT h.id AS hospital_id, h.name, h.lat, h.lng, c.available_capacity
               FROM capabilities c JOIN hospitals h ON h.id = c.hospital_id
               WHERE c.facility_type = ? AND c.available_capacity > 0 AND h.id != ?""",
            (ref["required_facility"], ref["referring_hospital_id"]),
        ).fetchall()

    ranked = rank_referral_matches(
        referral={
            "lat": referrer["lat"],
            "lng": referrer["lng"],
            "urgency": ref["urgency"],
            "preferred_radius_km": ref["preferred_radius_km"],
        },
        candidates=[dict(c) for c in candidates],
    )
    return ranked


@app.post("/referrals/accept")
def accept_referral(body: AcceptReferralBody):
    with db_session() as db:
        ref = db.execute("SELECT * FROM referrals WHERE id = ?", (body.referral_id,)).fetchone()
        if not ref:
            raise HTTPException(404, "Referral not found.")
        db.execute(
            "UPDATE referrals SET status = 'accepted', accepting_hospital_id = ? WHERE id = ?",
            (body.accepting_hospital_id, body.referral_id),
        )
        db.execute(
            "UPDATE capabilities SET available_capacity = MAX(available_capacity - 1, 0) "
            "WHERE hospital_id = ? AND facility_type = ?",
            (body.accepting_hospital_id, ref["required_facility"]),
        )
        db.execute(
            "UPDATE hospitals SET credit_balance = credit_balance + ? WHERE id = ?",
            (URGENCY_CREDIT.get(ref["urgency"], 5), body.accepting_hospital_id),
        )
    return {"status": "accepted"}


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

@app.get("/leaderboard")
def leaderboard():
    with db_session() as db:
        rows = db.execute(
            "SELECT name, credit_balance FROM hospitals ORDER BY credit_balance DESC"
        ).fetchall()
    return [
        {"rank": i + 1, "name": r["name"], "credit_balance": r["credit_balance"]}
        for i, r in enumerate(rows)
    ]
