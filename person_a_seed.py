"""
seed.py
Populates rhrn.db with 18 hospitals spread across real towns in and around
Telangana (since the team's based in Hyderabad — makes the map view during
the demo look like an actual regional network instead of random dots).

Every seeded hospital's login password is: demo123
(so whoever's driving the demo doesn't need a cheat sheet of 18 passwords)

Run: python seed.py
Re-running wipes and re-seeds, so it's safe to run again right before the
demo if the data gets messy during rehearsal.
"""

import random
from person_a_database import db_session, init_db
from person_a_auth import hash_password

random.seed(42)  # reproducible seed data — same "random" spread every run

# (name, approx lat, approx lng) — real towns, roughly matching real coords,
# with small jitter added per-hospital so multiple hospitals in the same
# town don't sit exactly on top of each other on the map.
TOWNS = [
    ("Hyderabad", 17.3850, 78.4867),
    ("Hyderabad", 17.3850, 78.4867),   # 2nd hospital, same city
    ("Warangal", 17.9689, 79.5941),
    ("Nizamabad", 18.6725, 78.0941),
    ("Karimnagar", 18.4386, 79.1288),
    ("Khammam", 17.2473, 80.1514),
    ("Nalgonda", 17.0575, 79.2685),
    ("Mahbubnagar", 16.7488, 77.9855),
    ("Adilabad", 19.6640, 78.5320),
    ("Suryapet", 17.1400, 79.6200),
    ("Siddipet", 18.1018, 78.8492),
    ("Miryalaguda", 16.8712, 79.5666),
    ("Jagtial", 18.7909, 78.9134),
    ("Mancherial", 18.8712, 79.4652),
    ("Sangareddy", 17.6270, 78.0866),
    ("Vikarabad", 17.3378, 77.9042),
    ("Medak", 18.0460, 78.2637),
    ("Kothagudem", 17.5504, 80.6183),
]

SUFFIXES = ["District Hospital", "General Hospital", "Government Hospital",
            "Medical College Hospital", "Community Health Centre"]

RESOURCE_TYPES = ["blood_o_neg", "oxygen_cylinder", "ventilator", "ambulance", "icu_bed"]
FACILITY_TYPES = ["cardiology", "neurosurgery", "dialysis", "nicu", "trauma_center"]

# Bigger towns (first 6 in the list) get richer inventory + more specialties,
# so ranked results actually look like a realistic rural/urban capacity gap.
BIG_TOWN_CUTOFF = 6


def jitter(coord, spread=0.06):
    return coord + random.uniform(-spread, spread)


def build_hospitals():
    hospitals = []
    for i, (town, lat, lng) in enumerate(TOWNS):
        suffix = random.choice(SUFFIXES)
        name = f"{town} {suffix}" if i < BIG_TOWN_CUTOFF else f"{town} {suffix}"
        # avoid literal duplicate names when a town appears twice
        if any(h["name"] == name for h in hospitals):
            name = f"{town} {suffix} #{i}"
        hospitals.append({
            "name": name,
            "lat": round(jitter(lat), 5),
            "lng": round(jitter(lng), 5),
            "contact_phone": f"+91-9{random.randint(100000000, 999999999)}",
            "is_big": i < BIG_TOWN_CUTOFF,
        })
    return hospitals


def seed():
    init_db()
    with db_session() as db:
        db.execute("DELETE FROM referrals")
        db.execute("DELETE FROM requests")
        db.execute("DELETE FROM capabilities")
        db.execute("DELETE FROM resources")
        db.execute("DELETE FROM sessions")
        db.execute("DELETE FROM hospitals")

        hospitals = build_hospitals()
        hospital_ids = []

        for h in hospitals:
            password_hash, salt = hash_password("demo123")
            cur = db.execute(
                """INSERT INTO hospitals (name, lat, lng, contact_phone, password_hash, salt, credit_balance)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (h["name"], h["lat"], h["lng"], h["contact_phone"], password_hash, salt,
                 random.randint(0, 40)),
            )
            hospital_ids.append((cur.lastrowid, h["is_big"]))

        for hospital_id, is_big in hospital_ids:
            # Inventory: big towns stock most resource types in decent
            # quantity; smaller ones stock fewer types, and thinner.
            n_types = random.randint(3, 5) if is_big else random.randint(1, 3)
            for resource_type in random.sample(RESOURCE_TYPES, n_types):
                qty_range = (10, 60) if is_big else (0, 12)
                qty = random.randint(*qty_range)
                unit = "units" if resource_type == "blood_o_neg" else \
                       "cylinders" if resource_type == "oxygen_cylinder" else \
                       "beds" if resource_type == "icu_bed" else "available"
                db.execute(
                    """INSERT INTO resources (hospital_id, resource_type, quantity, unit)
                       VALUES (?, ?, ?, ?)""",
                    (hospital_id, resource_type, qty, unit),
                )

            # Capabilities: only big towns and ~1/3 of small towns have any
            # named specialty — most rural centers legitimately don't, and
            # that gap is exactly what makes referral matching meaningful.
            if is_big:
                n_facilities = random.randint(2, 4)
            elif random.random() < 0.33:
                n_facilities = 1
            else:
                n_facilities = 0
            for facility_type in random.sample(FACILITY_TYPES, n_facilities):
                capacity = random.randint(3, 15) if is_big else random.randint(0, 3)
                db.execute(
                    """INSERT INTO capabilities (hospital_id, facility_type, available_capacity)
                       VALUES (?, ?, ?)""",
                    (hospital_id, facility_type, capacity),
                )

        print(f"Seeded {len(hospitals)} hospitals. All passwords: demo123")
        for h in hospitals:
            print(f"  - {h['name']}  ({h['lat']}, {h['lng']})")


if __name__ == "__main__":
    seed()
