"""
app.py - SOS Accident Emergency Alert System (Backend)
--------------------------------------------------------
Flask + SQLite backend that:

  1. Finds the nearest hospital (Haversine formula) to the patient's
     live GPS location.
  2. Sends up to 10 repeated "Emergency Alert" HTML emails (every
     ALERT_INTERVAL_SECONDS) to the nearest hospital's email AND the
     emergency contact's email. Each email has a siren .wav attached
     and an orange "CLICK HERE" button.
  3. "CLICK HERE" opens /acknowledge/<event_id> — a web page that shows
     the patient's EXACT location on an embedded map, and marks the
     alert acknowledged so the repeat emails stop early.
  4. Logs every SOS event into sos_events table.

Run:
    python3 app.py
Then open:
    http://127.0.0.1:5000
"""

import os
import base64
import tempfile
import sqlite3
import math
import time
import threading

import requests
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template

from voice_alert import generate_alert_audio

DB_NAME = "hospitals.db"

app = Flask(__name__)

# ------------------------------------------------------------------
# !! EMAIL CONFIG - SendGrid HTTP API !!
# Sends over HTTPS (port 443) instead of SMTP (port 587), which avoids
# the SMTP port being blocked on some networks.
#
# Required setup:
#   1. In SendGrid, verify a "Single Sender" (or authenticate a domain)
#      and put that verified address in SENDER_EMAIL below.
#   2. Put your SendGrid API key in a .env file next to app.py:
#        SENDGRID_API_KEY=SG.xxxxxxxx
#      (never hardcode the key directly in this file / commit it to git)
# ------------------------------------------------------------------
load_dotenv()

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "YOUR_VERIFIED_SENDGRID_SENDER@example.com")

# Base URL used inside emails for the "CLICK HERE" link.
# Change this to your deployed domain when you host it online.
BASE_URL = "http://10.75.31.200:5000"

NUM_ALERT_EMAILS = 10          # max number of repeated emails
ALERT_INTERVAL_SECONDS = 4     # gap between each repeated email (matches reference: "every 4 seconds")


# ------------------------------------------------------------------
# Haversine distance (km) between two lat/lon points
# ------------------------------------------------------------------
def list_contacts():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM emergency_contacts ORDER BY id")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def add_contact(name, relation, email):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO emergency_contacts (name, relation, email) VALUES (?, ?, ?)",
        (name, relation, email),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def delete_contact(contact_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM emergency_contacts WHERE id = ?", (contact_id,))
    conn.commit()
    conn.close()


def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    c = 2 * math.asin(math.sqrt(a))
    return R * c


def find_nearest_hospital(lat, lon):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM hospitals")
    hospitals = cur.fetchall()
    conn.close()

    nearest = None
    nearest_dist = float("inf")
    for h in hospitals:
        d = haversine(lat, lon, h["latitude"], h["longitude"])
        if d < nearest_dist:
            nearest_dist = d
            nearest = h

    if nearest is None:
        return None

    return {
        "id": nearest["id"],
        "name": nearest["name"],
        "latitude": nearest["latitude"],
        "longitude": nearest["longitude"],
        "email": nearest["email"],
        "distance_km": round(nearest_dist, 2),
    }


def create_sos_event(patient_name, contact_emails, lat, lon, hospital):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO sos_events
            (patient_name, contact_emails, patient_lat, patient_lon,
             hospital_id, hospital_name, hospital_email, acknowledged)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
    """, (patient_name, ",".join(contact_emails), lat, lon, hospital["id"], hospital["name"], hospital["email"]))
    conn.commit()
    event_id = cur.lastrowid
    conn.close()
    return event_id


def is_acknowledged(event_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT acknowledged FROM sos_events WHERE id = ?", (event_id,))
    row = cur.fetchone()
    conn.close()
    return bool(row and row[0] == 1)


def mark_acknowledged(event_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE sos_events SET acknowledged = 1 WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()


def is_viewed(event_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT viewed FROM sos_events WHERE id = ?", (event_id,))
    row = cur.fetchone()
    conn.close()
    return bool(row and row[0] == 1)


def mark_viewed(event_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE sos_events SET viewed = 1 WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()


def get_hospital_by_id(hospital_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM hospitals WHERE id = ?", (hospital_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_event(event_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM sos_events WHERE id = ?", (event_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def build_hospital_email(patient_name, lat, lon, hospital, seq, event_id, audio_path):
    """Email sent to the HOSPITAL — its 'CLICK HERE' opens the acknowledge
    page, which gives directions TO THE PATIENT (the hospital needs to
    reach the patient)."""
    view_link = f"{BASE_URL}/acknowledge/{event_id}"

    subject = f"🚨 Emergency Alert - Patient near {hospital['name']}"

    text_body = f"""INCOMING EMERGENCY
Patient near {hospital['name']}

Patient: {patient_name}
Location: {lat}, {lon}

This alert repeats every {ALERT_INTERVAL_SECONDS} seconds until you tap the link below.

View exact location + get directions to patient: {view_link}
"""

    html_body = f"""
    <div style="background:#12141a;padding:28px;border-radius:14px;max-width:480px;
                font-family:Arial,Helvetica,sans-serif;color:#e8e8e8;">
        <p style="color:#f5a623;letter-spacing:1px;font-size:12px;font-weight:bold;margin:0 0 8px;">
            INCOMING EMERGENCY
        </p>
        <h2 style="margin:0 0 16px;font-size:24px;color:#ffffff;">
            Patient near {hospital['name']}
        </h2>
        <p style="margin:4px 0;color:#bbb;">Patient: {patient_name}</p>
        <p style="margin:4px 0 20px;color:#bbb;">Location: {lat}, {lon}</p>
        <p style="margin:0 0 20px;color:#888;font-size:13px;">
            This alert repeats every {ALERT_INTERVAL_SECONDS} seconds until you tap the button below.
        </p>
        <a href="{view_link}"
           style="display:inline-block;background:#f5a623;color:#1a1a1a;font-weight:bold;
                  padding:14px 26px;border-radius:8px;text-decoration:none;font-size:15px;">
            ✓ CLICK HERE — Directions to Patient
        </a>
        <p style="margin-top:18px;font-size:12px;color:#666;">
            (A spoken "Emergency Alert" voice message is attached to this email)
        </p>
    </div>
    <img src="{BASE_URL}/pixel/{event_id}.png" width="1" height="1" style="display:none;" alt="">
    """

    return _build_mime_email(subject, text_body, html_body, seq, audio_path)


def build_family_email(patient_name, lat, lon, hospital, seq, event_id, audio_path):
    """Email sent to a saved EMERGENCY CONTACT — its button gives directions
    TO THE HOSPITAL (the family needs to go meet the patient/ambulance
    there), not to the patient's roadside location."""
    hospital_directions_link = (
        f"https://www.google.com/maps/dir/?api=1"
        f"&destination={hospital['latitude']},{hospital['longitude']}"
    )

    subject = f"🚨 Emergency Alert - {patient_name} near {hospital['name']}"

    text_body = f"""INCOMING EMERGENCY
{patient_name} has met with an accident.
Nearest hospital: {hospital['name']}

This alert repeats every {ALERT_INTERVAL_SECONDS} seconds until you tap the link below.

Get directions to the hospital: {hospital_directions_link}
"""

    html_body = f"""
    <div style="background:#12141a;padding:28px;border-radius:14px;max-width:480px;
                font-family:Arial,Helvetica,sans-serif;color:#e8e8e8;">
        <p style="color:#f5a623;letter-spacing:1px;font-size:12px;font-weight:bold;margin:0 0 8px;">
            INCOMING EMERGENCY
        </p>
        <h2 style="margin:0 0 16px;font-size:24px;color:#ffffff;">
            {patient_name} near {hospital['name']}
        </h2>
        <p style="margin:4px 0 20px;color:#bbb;">Nearest hospital: {hospital['name']}</p>
        <p style="margin:0 0 20px;color:#888;font-size:13px;">
            This alert repeats every {ALERT_INTERVAL_SECONDS} seconds until you tap the button below.
        </p>
        <a href="{hospital_directions_link}"
           style="display:inline-block;background:#f5a623;color:#1a1a1a;font-weight:bold;
                  padding:14px 26px;border-radius:8px;text-decoration:none;font-size:15px;">
            🧭 GET DIRECTIONS TO HOSPITAL
        </a>
        <p style="margin-top:18px;font-size:12px;color:#666;">
            (A spoken "Emergency Alert" voice message is attached to this email)
        </p>
    </div>
    <img src="{BASE_URL}/pixel/{event_id}.png" width="1" height="1" style="display:none;" alt="">
    """

    return _build_mime_email(subject, text_body, html_body, seq, audio_path)


def _build_mime_email(subject, text_body, html_body, seq, audio_path):
    """Builds a plain dict describing the email (subject/text/html/attachment).
    Kept independent of 'To' address so the same dict can be reused per
    recipient, mirroring the old MIME builder's shape."""
    email = {
        "subject": f"{subject} (#{seq}/{NUM_ALERT_EMAILS})",
        "text_body": text_body,
        "html_body": html_body,
        "attachment_path": None,
        "attachment_filename": None,
    }

    # Attach the personalized siren + spoken "Emergency Alert" voice message
    # (skipped gracefully if audio generation failed for any reason)
    if audio_path and os.path.exists(audio_path):
        email["attachment_path"] = audio_path
        email["attachment_filename"] = "emergency_alert.wav"

    return email


def send_via_sendgrid(to_addr, subject, text_body, html_body, attachment_path=None, attachment_filename=None):
    """Sends a single email via the SendGrid HTTP API (port 443)."""
    if not SENDGRID_API_KEY:
        print("[EMAIL] SENDGRID_API_KEY is not set — add it to your .env file.")
        return False

    payload = {
        "personalizations": [{"to": [{"email": to_addr}]}],
        "from": {"email": SENDER_EMAIL},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": text_body},
            {"type": "text/html", "value": html_body},
        ],
    }

    if attachment_path and os.path.exists(attachment_path):
        try:
            with open(attachment_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode()
            payload["attachments"] = [{
                "content": encoded,
                "filename": attachment_filename or "attachment.wav",
                "type": "audio/wav",
                "disposition": "attachment",
            }]
        except Exception as e:
            print(f"[VOICE] Could not attach audio file: {e}")

    try:
        resp = requests.post(
            SENDGRID_API_URL,
            headers={
                "Authorization": f"Bearer {SENDGRID_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
        if resp.status_code in (200, 201, 202):
            print(f"[EMAIL] Sent to {to_addr}")
            return True
        print(f"[EMAIL] Failed to send to {to_addr}: {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        print(f"[EMAIL] Could not reach SendGrid API: {e}")
        return None


def send_alert_emails_background(event_id, patient_name, contact_emails, hospital, lat, lon):
    """Sends up to NUM_ALERT_EMAILS emails, one every ALERT_INTERVAL_SECONDS,
    to the hospital AND every saved emergency contact — stopping early the
    moment someone taps CLICK HERE (acknowledged = 1).

    A fresh SMTP login is made for EVERY single email (not shared across
    recipients or rounds). This is because Gmail can drop the connection
    right after rejecting an invalid/placeholder recipient address, which
    previously caused 'SMTPServerDisconnected: please run connect() first'
    for whichever recipient was sent next on that same connection.
    """
    recipients = [hospital["email"]] + list(contact_emails)

    # Generate the personalized siren + spoken voice alert once — the
    # message text is the same for every repeat of this event.
    audio_path = os.path.join(tempfile.gettempdir(), f"alert_{event_id}.wav")
    try:
        generate_alert_audio(patient_name, hospital["name"], audio_path)
    except Exception as e:
        print(f"[VOICE] Could not generate voice alert audio: {e}")
        audio_path = None

    def send_one(to_addr, email):
        """Sends a single email via the SendGrid API — fully independent
        of every other send (one HTTPS request per recipient)."""
        return send_via_sendgrid(
            to_addr,
            email["subject"],
            email["text_body"],
            email["html_body"],
            attachment_path=email["attachment_path"],
            attachment_filename=email["attachment_filename"],
        )

    for seq in range(1, NUM_ALERT_EMAILS + 1):
        if is_acknowledged(event_id):
            print(f"[EMAIL] Event {event_id} acknowledged — stopping repeats.")
            break
        if is_viewed(event_id):
            print(f"[EMAIL] Event {event_id} was viewed (opened) — stopping repeats.")
            break

        api_reachable = None
        for to_addr in recipients:
            # Hospital gets directions TO THE PATIENT; every saved family
            # contact gets directions TO THE HOSPITAL.
            if to_addr == hospital["email"]:
                email = build_hospital_email(patient_name, lat, lon, hospital, seq, event_id, audio_path)
            else:
                email = build_family_email(patient_name, lat, lon, hospital, seq, event_id, audio_path)
            result = send_one(to_addr, email)
            if result is None:
                # SendGrid API itself is unreachable / key missing — no
                # point retrying further recipients or rounds.
                api_reachable = False
                break

        if api_reachable is False:
            break

        time.sleep(ALERT_INTERVAL_SECONDS)

    if audio_path:
        try:
            os.remove(audio_path)
        except FileNotFoundError:
            pass

    print(f"[EMAIL] Alert loop finished for event {event_id}.")


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------
ESCALATION_WINDOW_SECONDS = 30   # total time budget: trigger -> fully notified
# Staged checkpoints within the 30s window (used by the frontend):
#   0s  -> SOS triggered, cancel window starts
#   5s  -> CALL AMBULANCE button is emphasized (kept visible throughout for
#          safety — an emergency call button should never be hidden)
#   10s -> cancel window ends, GPS location capture begins
#   20s -> nearest hospital identified
#   25s -> notifying emergency contacts
#   30s -> alert fully sent
CANCEL_WINDOW_SECONDS = 10       # grace period during which the user can cancel


def send_family_notification(patient_name, contact_emails, hospital_name, hospital_lat, hospital_lon, patient_lat, patient_lon):
    """Sent to every saved emergency contact the moment the hospital taps
    'CLICK HERE' — confirms the hospital has received the patient's
    location and gives the family directions TO THE HOSPITAL, starting
    from wherever the family member is when they open the link."""
    hospital_directions_link = (
        f"https://www.google.com/maps/dir/?api=1"
        f"&destination={hospital_lat},{hospital_lon}"
    )

    subject = f"✅ {hospital_name} has received {patient_name}'s location"
    text_body = f"""GOOD NEWS

{hospital_name} has received {patient_name}'s SOS alert and exact location.
Help is on the way.

Get directions to the hospital: {hospital_directions_link}
"""
    html_body = f"""
    <div style="background:#12141a;padding:28px;border-radius:14px;max-width:480px;
                font-family:Arial,Helvetica,sans-serif;color:#e8e8e8;">
        <p style="color:#2ecc71;letter-spacing:1px;font-size:12px;font-weight:bold;margin:0 0 8px;">
            HOSPITAL RESPONDING
        </p>
        <h2 style="margin:0 0 16px;font-size:22px;color:#ffffff;">
            {hospital_name} has received {patient_name}'s location
        </h2>
        <p style="margin:4px 0 20px;color:#bbb;">Help is on the way.</p>
        <a href="{hospital_directions_link}"
           style="display:inline-block;background:#2ecc71;color:#0c1a12;font-weight:bold;
                  padding:14px 26px;border-radius:8px;text-decoration:none;font-size:15px;">
            🧭 Get Directions to Hospital
        </a>
    </div>
    """

    for contact_email in contact_emails:
        ok = send_via_sendgrid(contact_email, subject, text_body, html_body)
        if ok:
            print(f"[EMAIL] Notified {contact_email} that hospital received the alert.")
        else:
            print(f"[EMAIL] Could not notify {contact_email} of hospital acknowledgment.")


@app.route("/")
def index():
    return render_template(
        "index.html",
        ESCALATION_WINDOW=ESCALATION_WINDOW_SECONDS,
        CANCEL_WINDOW=CANCEL_WINDOW_SECONDS,
    )


@app.route("/admin")
def admin():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM sos_events ORDER BY id DESC")
    events = [dict(row) for row in cur.fetchall()]
    conn.close()
    return render_template("admin.html", events=events)


@app.route("/api/contacts", methods=["GET"])
def get_contacts():
    return jsonify(list_contacts())


@app.route("/api/contacts", methods=["POST"])
def create_contact():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    relation = (data.get("relation") or "").strip()
    email = (data.get("email") or "").strip()

    if not name or not email:
        return jsonify({"error": "name and email are required"}), 400

    new_id = add_contact(name, relation, email)
    return jsonify({"id": new_id, "name": name, "relation": relation, "email": email})


@app.route("/api/contacts/<int:contact_id>", methods=["DELETE"])
def remove_contact(contact_id):
    delete_contact(contact_id)
    return jsonify({"status": "deleted", "id": contact_id})


@app.route("/api/sos", methods=["POST"])
def sos():
    data = request.get_json(force=True)

    patient_name = data.get("patient_name", "Unknown Patient")
    lat = data.get("latitude")
    lon = data.get("longitude")

    if lat is None or lon is None:
        return jsonify({"error": "latitude/longitude required"}), 400

    # Contacts are pre-saved ahead of time (see /api/contacts) — an accident
    # victim can't be expected to type an email address in the moment, so
    # SOS always notifies every contact already saved in the database.
    contacts = list_contacts()
    if not contacts:
        return jsonify({"error": "No emergency contacts saved yet. Add at least one contact first."}), 400
    contact_emails = [c["email"] for c in contacts]

    lat, lon = float(lat), float(lon)

    hospital = find_nearest_hospital(lat, lon)
    if hospital is None:
        return jsonify({"error": "No hospitals found in database"}), 404

    event_id = create_sos_event(patient_name, contact_emails, lat, lon, hospital)

    t = threading.Thread(
        target=send_alert_emails_background,
        args=(event_id, patient_name, contact_emails, hospital, lat, lon),
        daemon=True,
    )
    t.start()

    maps_link = f"https://www.google.com/maps?q={lat},{lon}"
    hospital_maps_link = f"https://www.google.com/maps?q={hospital['latitude']},{hospital['longitude']}"

    return jsonify({
        "status": "SOS triggered",
        "event_id": event_id,
        "nearest_hospital": hospital,
        "patient_location_maps_link": maps_link,
        "hospital_location_maps_link": hospital_maps_link,
        "emails_queued": NUM_ALERT_EMAILS,
        "contacts_notified": len(contact_emails),
    })


@app.route("/pixel/<int:event_id>.png")
def tracking_pixel(event_id):
    """A 1x1 transparent PNG embedded (invisibly) in every alert email.
    When the recipient's mail client loads images — which normally happens
    the moment they open/view the email, even without clicking any link —
    this marks the event as 'viewed' so the repeat-email loop stops."""
    if not is_viewed(event_id):
        mark_viewed(event_id)
        print(f"[EMAIL] Event {event_id} email was opened (tracking pixel loaded).")

    # Smallest valid 1x1 transparent PNG, as raw bytes
    pixel = bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001080600000"
        "01f15c4890000000a49444154789c6360000002000100"
        "00050001a8b71f7b0000000049454e44ae426082"
    )
    return pixel, 200, {"Content-Type": "image/png"}


@app.route("/acknowledge/<int:event_id>")
def acknowledge(event_id):
    """The page opened when someone taps 'CLICK HERE' in the email.
    Shows the patient's EXACT location on an embedded map and stops
    further repeat emails for this event."""
    event = get_event(event_id)
    if event is None:
        return "<h2 style='font-family:sans-serif;text-align:center;margin-top:60px;'>Alert not found.</h2>", 404

    mark_acknowledged(event_id)

    # Notify every saved contact that the hospital has now received the
    # location, with directions TO THE HOSPITAL (in a background thread so
    # the hospital's page loads instantly)
    contact_emails = [e for e in (event["contact_emails"] or "").split(",") if e]
    hospital = get_hospital_by_id(event["hospital_id"])
    t = threading.Thread(
        target=send_family_notification,
        args=(event["patient_name"], contact_emails, event["hospital_name"],
              hospital["latitude"] if hospital else event["patient_lat"],
              hospital["longitude"] if hospital else event["patient_lon"],
              event["patient_lat"], event["patient_lon"]),
        daemon=True,
    )
    t.start()

    return render_template(
        "acknowledge.html",
        patient_name=event["patient_name"],
        hospital_name=event["hospital_name"],
        lat=event["patient_lat"],
        lon=event["patient_lon"],
        hospital_lat=hospital["latitude"] if hospital else event["patient_lat"],
        hospital_lon=hospital["longitude"] if hospital else event["patient_lon"],
    )


if __name__ == "__main__":
    # host="0.0.0.0" makes the server reachable from other devices (like a
    # phone) on the same WiFi network — not just from this laptop itself.
    app.run(debug=True, host="0.0.0.0", port=5000)
