# 🚨 SOS Guard — Highway Accident Emergency Alert System

Frontend: HTML, CSS, JS (dark "SOS Guard" theme, responsive for laptop + mobile)
Backend: Python (Flask), SQLite

## Setup

```bash
pip install -r requirements.txt
python database.py      # creates hospitals.db + seeds Tiruvannamalai hospitals
python app.py             # starts server at http://127.0.0.1:5000
```

> On Windows, if `python3` gives "not found", use `python` instead (as above).

Open **http://127.0.0.1:5000** on this laptop, or `http://<laptop-LAN-IP>:5000`
from a phone on the same WiFi (see "Laptop vs Mobile" below).

## First-time setup: save Emergency Contacts

An accident victim can't be expected to type an email address while
injured — so contacts are saved **once, ahead of time**, in the
"EMERGENCY CONTACTS" card on the main page (Name, Relation, Email). SOS
automatically notifies every saved contact — no typing needed during the
actual emergency. Add at least one contact before testing SOS, or the
button will show an error.

## Before it can send real emails

Edit these lines in `app.py`:

```python
SENDER_EMAIL = "YOUR_SENDER_EMAIL@gmail.com"
SENDER_APP_PASSWORD = "YOUR_16_CHAR_APP_PASSWORD"
BASE_URL = "http://<your-laptop-LAN-IP>:5000"   # NOT 127.0.0.1 if phones will click email links
```

Gmail App Password (NOT your normal Gmail password):
1. Turn on 2-Step Verification on your Google account
2. Go to https://myaccount.google.com/apppasswords
3. Generate a 16-character app password for "Mail"
4. Paste it in `SENDER_APP_PASSWORD`

### "Address not found" bounce-back emails

Hospital emails in `database.py` may still be placeholders
(`arunai.demo@example.com`, etc.) — `example.com` isn't a real mail domain,
so Gmail will always bounce those. Replace with real hospital emails,
delete `hospitals.db`, and re-run `python database.py`.

## Laptop vs Mobile — location handling

- **Mobile**: uses the phone's real GPS via the browser's Geolocation API.
  Chrome requires a "secure origin" for this — if you're opening the app
  over `http://<LAN-IP>:5000` (not `localhost`), enable this once per
  browser:
  1. Visit `chrome://flags/#unsafely-treat-insecure-origin-as-secure`
  2. Set it to **Enabled**, add `http://<LAN-IP>:5000` in the text box
  3. Relaunch Chrome
- **Laptop/Desktop**: most laptops have no GPS chip. Tick
  **"No GPS on this device? Enter location manually"** above the SOS
  button, type coordinates (or tap **"OPEN DEMO"** to auto-fill sample
  Tiruvannamalai coordinates) — this skips waiting for GPS entirely.
- **Testing on an actual phone**: open the app in the phone's own browser
  using the laptop's LAN IP (`ipconfig` on the laptop → IPv4 Address),
  both devices on the same WiFi, mobile data off.
- **Accurate location options on a laptop** (no GPS chip), most → least
  practical: (1) type coordinates read off your phone's Maps app —
  100% accurate, free; (2) a USB GPS dongle — real hardware fix, ~3-5m
  accuracy; (3) the browser's built-in WiFi-based geolocation — works
  automatically, medium accuracy; (4) IP-based geolocation — city-level
  only, not accurate enough for real use.

## How it works — the 30-second escalation window

1. Tap the big **SOS** button.
2. **+0-10s**: grace period to cancel ("Cancel alert — I'm okay") if it was
   a false alarm. The ring around the button fills in to show progress.
3. **+5s**: the **CALL AMBULANCE (108)** button gets a brief emphasis pulse
   — it's always visible and clickable the entire time (an emergency call
   button should never be hidden for a "reveal" effect).
4. **+10s**: if not cancelled, GPS location is captured (device GPS, or
   your manual entry) — button shows "LOCATING". The real request to the
   backend fires immediately here so hospital/contacts are notified as
   fast as possible; the checkpoints below only pace what's *shown on
   screen*, not the actual notification speed.
5. **+20s**: "Nearest hospital identified" appears in the log (Haversine
   distance against the `hospitals` table).
6. **+25s**: "Notifying emergency contacts..." appears.
7. **+30s**: button shows "SENT", ring turns full green.

## Who gets directions to where

- **Hospital's email** → "CLICK HERE" opens an exact-location page with
  **directions TO THE PATIENT** (the hospital/ambulance needs to reach
  the accident site).
- **Every saved emergency contact's email** → a "GET DIRECTIONS TO
  HOSPITAL" button (the family needs to reach the hospital, not the
  roadside location; opens with their own current location as the
  starting point).
- The moment the **hospital** taps CLICK HERE: (a) repeat emails stop for
  everyone, and (b) every contact gets a follow-up "✅ Hospital has
  received the location" email — also with directions to the hospital.

## Repeat emails also stop just by opening the email (no click needed)

Every alert email has an invisible 1x1 tracking pixel. The moment the
recipient's mail app loads images — which normally happens the instant
they open/view the email, even without tapping anything — the repeat
loop stops for everyone. Tapping "CLICK HERE" still does the extra
acknowledgment steps (family follow-up email, exact-location page), but
simply viewing the email is now enough to stop the spam of repeats.
The admin dashboard shows "Viewed (not clicked)" vs "Acknowledged" vs
"Pending" accordingly.

## Live spoken narration (girl voice) during the SOS process

As each step of the 30-second process happens on screen — "SOS
triggered", "GPS location captured", "Nearest hospital identified",
"Notifying emergency contacts", etc. — it's also **spoken aloud** using
the browser's built-in Text-to-Speech, automatically picking a female
voice if the device has one installed (e.g. Chrome/Android's default
female voices, or "Microsoft Zira" on Windows). No setup needed.

Every alert email also has a real **siren + spoken "Emergency Alert"
voice message** attached as a `.wav`, synthesized offline via `pyttsx3`
(Windows SAPI5 / Mac NSSpeech / Linux espeak), also preferring a female
voice when one is available on the machine running the server.

## Admin Dashboard

**VIEW ADMIN DASHBOARD** (`/admin`) shows every past SOS event — patient,
contacts notified, hospital, exact location link, and acknowledgment status.

## Files

```
sos_project/
├── app.py                    -> Flask backend: SOS API, contacts API, haversine, email sender, acknowledge + admin routes
├── voice_alert.py             -> generates siren + spoken "Emergency Alert" voice .wav (pyttsx3, offline)
├── database.py                -> creates + seeds hospitals.db (hospitals, emergency_contacts, sos_events)
├── requirements.txt
├── templates/
│   ├── index.html             -> SOS Guard main page (contacts card, stats bar, 30s staged SOS)
│   ├── acknowledge.html       -> exact-location map + directions-to-patient page (opened from hospital's email)
│   └── admin.html             -> SOS event history dashboard
└── static/
    ├── style.css               -> dark SOS Guard theme, responsive laptop+mobile
    └── script.js               -> contacts CRUD, 30s staged process, progress ring, geolocation + manual fallback
```

## Customize

- **More/real hospitals**: edit `HOSPITALS` in `database.py` → delete
  `hospitals.db` → re-run `python database.py`.
- **Number of alert emails / interval**: `NUM_ALERT_EMAILS`,
  `ALERT_INTERVAL_SECONDS` in `app.py`.
- **Voice message wording**: edit the `message` string inside
  `generate_alert_audio()` in `voice_alert.py`.
- **30s escalation schedule**: `ESCALATION_WINDOW_SECONDS`,
  `CANCEL_WINDOW_SECONDS` in `app.py`; matching `CANCEL_WINDOW_SECONDS`,
  `CALL_EMPHASIZE_AT`, `HOSPITAL_REVEAL_AT`, `NOTIFY_REVEAL_AT` in
  `static/script.js`.
- **Deploying online**: once hosted (e.g. Render/Railway), update
  `BASE_URL` in `app.py` to your live HTTPS domain.
