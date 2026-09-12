"""
auth.py
Deliberately minimal: salted SHA-256 password hashing + a random session
token stored in the `sessions` table. No OAuth, no JWT — this is a
36-hour hackathon, not a bank.

NOTE for the team: the current frontend only reads `hospital_id` from the
login response and doesn't send a session token back on later requests, so
those other endpoints trust whatever hospital_id is passed in. That's a
known shortcut, not an oversight — if there's spare time before the demo,
the easy upgrade is to also return `token` from /auth/login, have the
frontend store it and send it as `Authorization: Bearer <token>`, and add
a `get_current_hospital(token)` dependency to the write endpoints. Skipped
for now to keep scope small; flagging so nobody "discovers" it as a bug
mid-demo.
"""

import hashlib
import os
import secrets


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Returns (password_hash, salt). Generates a new salt if none given."""
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return digest, salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    digest, _ = hash_password(password, salt)
    return secrets.compare_digest(digest, password_hash)


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)
