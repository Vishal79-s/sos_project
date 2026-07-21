"""
database.py
------------
Creates hospitals.db (SQLite) and seeds it with the hospital list for
Tiruvannamalai (TVM) — name, latitude, longitude, email.

Run once:  python database.py

NOTE on accuracy (double-checked against public sources):
- "Government Medical College & Hospital (GTVMMC&H)" coordinates were
  corrected. The originally supplied coordinates (12.274351, 79.079113)
  were ~6km off from the hospital's real location. Corrected value below
  (12.225987, 79.066088) is independently verified via Wikipedia
  (Government Tiruvannamalai Medical College and Hospital).
- Arunai Medical College, KVS Medical Center: addresses were confirmed via
  public directories/registries and are consistent with the supplied
  coordinates' area, but exact pin-level accuracy wasn't independently
  verifiable from text sources alone.
- Amudham Hospitals, Suriyan Hospital, Vasantha Hospital: could not be
  independently verified beyond what was supplied — coordinates kept
  as originally given.
- For guaranteed-accurate pins on any entry: open Google Maps -> search
  the hospital name -> long-press the pin -> copy the lat/long shown at
  the bottom, then update the HOSPITALS list below.
- Real email addresses were not provided for these hospitals, so
  placeholder emails are used below. Edit the HOSPITALS list with the
  real contact emails, delete hospitals.db, and re-run this file.

NOTE on emergency_contacts:
- Emergency contacts are now saved PERMANENTLY ahead of time (Name,
  Relation, Email) via the app's "Emergency Contacts" section, instead of
  being typed in at the moment of the SOS — an accident victim can't be
  expected to type an email address while injured. When SOS triggers, it
  automatically notifies every saved contact.
"""

import sqlite3

DB_NAME = "hospitals.db"

HOSPITALS = [
    ("Arunai Medical College and Hospital",              12.190021, 79.081960, "govthospitals17@gmail.com"),
    ("Amudham Hospitals",                                 12.217089, 79.059782, "govthospitals17@gmail.com"),
    ("Government Medical College & Hospital (GTVMMC&H)",  12.225987, 79.066088, "govthospitals17@gmail.com"),
    ("KVS Medical Center and Research Institute",         12.229651, 79.064934, "govthospitals17@gmail.com"),
    ("Suriyan Hospital",                                  12.230854, 79.081025, "govthospitals17@gmail.com"),
    ("Vasantha Hospital and Wellness",                    12.236077, 79.070883, "govthospitals17@gmail.com"),
]


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS hospitals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            email TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS emergency_contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            relation TEXT,
            email TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sos_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name TEXT,
            contact_emails TEXT,
            patient_lat REAL,
            patient_lon REAL,
            hospital_id INTEGER,
            hospital_name TEXT,
            hospital_email TEXT,
            acknowledged INTEGER DEFAULT 0,
            viewed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("SELECT COUNT(*) FROM hospitals")
    count = cur.fetchone()[0]

    if count == 0:
        cur.executemany(
            "INSERT INTO hospitals (name, latitude, longitude, email) VALUES (?, ?, ?, ?)",
            HOSPITALS
        )
        print(f"Seeded {len(HOSPITALS)} hospitals into {DB_NAME}")
    else:
        print(f"hospitals table already has {count} rows — skipped seeding")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
