const sosBtn = document.getElementById("sosBtn");
const sosBtnText = document.getElementById("sosBtnText");
const sosBtnSub = document.getElementById("sosBtnSub");
const cancelBtn = document.getElementById("cancelBtn");
const callBtn = document.getElementById("callBtn");
const statusBadge = document.getElementById("statusBadge");
const logEl = document.getElementById("log");
const errorBox = document.getElementById("errorBox");
const patientNameInput = document.getElementById("patientName");
const howBtn = document.getElementById("howBtn");
const howPanel = document.getElementById("howPanel");
const demoBtn = document.getElementById("demoBtn");
const manualLocationBox = document.getElementById("manualLocationBox");
const manualLat = document.getElementById("manualLat");
const manualLon = document.getElementById("manualLon");
const useManualBtn = document.getElementById("useManualBtn");
const progressRingFg = document.getElementById("progressRingFg");
const manualToggle = document.getElementById("manualToggle");
const manualUpfrontBox = document.getElementById("manualUpfrontBox");
const manualLatUpfront = document.getElementById("manualLatUpfront");
const manualLonUpfront = document.getElementById("manualLonUpfront");
const contactsList = document.getElementById("contactsList");
const newContactName = document.getElementById("newContactName");
const newContactRelation = document.getElementById("newContactRelation");
const newContactEmail = document.getElementById("newContactEmail");
const addContactBtn = document.getElementById("addContactBtn");
const contactsError = document.getElementById("contactsError");

manualToggle.addEventListener("change", () => {
  manualUpfrontBox.classList.toggle("hidden", !manualToggle.checked);
});

// Checkpoints within the ESCALATION_WINDOW_SECONDS (30s) — matches app.py:
//   0s SOS triggered · 5s emphasize call button · 10s cancel ends / GPS ·
//   20s hospital identified · 25s notifying contacts · 30s sent
const CANCEL_WINDOW_SECONDS = 10;
const CALL_EMPHASIZE_AT = 5;
const HOSPITAL_REVEAL_AT = 20;
const NOTIFY_REVEAL_AT = 25;
const RING_CIRCUMFERENCE = 2 * Math.PI * 82; // matches r=82 in the SVG circle

let startTime = null;
let cancelTimer = null;
let cancelled = false;
let sosActive = false;
let pendingManualResolve = null; // resolves with {lat, lon} once user submits manual coords
let ringInterval = null;
let stagedTimers = []; // all setTimeouts for the 5/20/25/30s checkpoints — cleared on cancel

// ---------------- Emergency Contacts (saved permanently — no typing
// needed from the patient during an actual emergency) ----------------
async function loadContacts() {
  try {
    const res = await fetch("/api/contacts");
    const contacts = await res.json();
    renderContacts(contacts);
  } catch (err) {
    console.error("Could not load contacts:", err);
  }
}

function renderContacts(contacts) {
  contactsList.innerHTML = "";
  if (contacts.length === 0) {
    contactsList.innerHTML = '<p class="contacts-empty">No emergency contacts saved yet — add at least one below.</p>';
    return;
  }
  contacts.forEach((c) => {
    const row = document.createElement("div");
    row.className = "contact-row";

    const avatar = document.createElement("div");
    avatar.className = "contact-avatar";
    avatar.textContent = (c.name || "?").charAt(0).toUpperCase();

    const info = document.createElement("div");
    info.className = "contact-info";
    const nameEl = document.createElement("div");
    nameEl.className = "contact-name";
    nameEl.textContent = c.name;
    const metaEl = document.createElement("div");
    metaEl.className = "contact-meta";
    metaEl.textContent = c.relation ? `${c.relation} · ${c.email}` : c.email;
    info.appendChild(nameEl);
    info.appendChild(metaEl);

    const removeBtn = document.createElement("button");
    removeBtn.className = "contact-remove-btn";
    removeBtn.textContent = "−";
    removeBtn.addEventListener("click", () => removeContact(c.id));

    row.appendChild(avatar);
    row.appendChild(info);
    row.appendChild(removeBtn);
    contactsList.appendChild(row);
  });
}

async function removeContact(id) {
  try {
    await fetch(`/api/contacts/${id}`, { method: "DELETE" });
    loadContacts();
  } catch (err) {
    console.error("Could not remove contact:", err);
  }
}

addContactBtn.addEventListener("click", async () => {
  contactsError.classList.add("hidden");
  const name = newContactName.value.trim();
  const relation = newContactRelation.value.trim();
  const email = newContactEmail.value.trim();

  if (!name || !email) {
    contactsError.textContent = "⚠️ Name and Email are required.";
    contactsError.classList.remove("hidden");
    return;
  }

  try {
    const res = await fetch("/api/contacts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, relation, email }),
    });
    if (!res.ok) {
      const data = await res.json();
      contactsError.textContent = "⚠️ " + (data.error || "Could not add contact.");
      contactsError.classList.remove("hidden");
      return;
    }
    newContactName.value = "";
    newContactRelation.value = "";
    newContactEmail.value = "";
    loadContacts();
  } catch (err) {
    contactsError.textContent = "⚠️ Could not reach the server.";
    contactsError.classList.remove("hidden");
  }
});

loadContacts();

// ---------------- Progress ring ----------------
function setRingProgress(fraction, stateClass) {
  const clamped = Math.max(0, Math.min(1, fraction));
  progressRingFg.style.strokeDashoffset = RING_CIRCUMFERENCE * (1 - clamped);
  progressRingFg.classList.remove("confirming", "locating", "sent");
  if (stateClass) progressRingFg.classList.add(stateClass);
}

function startRingAnimation() {
  clearInterval(ringInterval);
  ringInterval = setInterval(() => {
    const secs = (Date.now() - startTime) / 1000;
    const fraction = secs / ESCALATION_WINDOW_SECONDS;
    const stateClass = secs < CANCEL_WINDOW_SECONDS ? "confirming" : "locating";
    setRingProgress(fraction, stateClass);
  }, 100);
}

function stopRingAnimation(finalFraction, stateClass) {
  clearInterval(ringInterval);
  ringInterval = null;
  if (finalFraction !== undefined) setRingProgress(finalFraction, stateClass);
}

function elapsed() {
  return Math.round((Date.now() - startTime) / 1000);
}

// ---------------- Live spoken narration (girl voice) for every SOS step ----------------
let cachedFemaleVoice = null;
let voicesReady = false;

function pickFemaleVoice() {
  const voices = window.speechSynthesis ? window.speechSynthesis.getVoices() : [];
  if (!voices.length) return null;
  const female = voices.find((v) =>
    /female|zira|samantha|susan|woman|girl/i.test(v.name) ||
    /female/i.test(v.voiceURI || "")
  );
  return female || voices.find((v) => /en/i.test(v.lang)) || voices[0] || null;
}

if (window.speechSynthesis) {
  // Voices often load asynchronously — refresh our pick once they're ready.
  window.speechSynthesis.onvoiceschanged = () => {
    cachedFemaleVoice = pickFemaleVoice();
    voicesReady = true;
  };
  cachedFemaleVoice = pickFemaleVoice();
}

function speak(text) {
  if (!window.speechSynthesis) return;
  try {
    window.speechSynthesis.cancel(); // don't stack overlapping announcements
    const utter = new SpeechSynthesisUtterance(text);
    const voice = cachedFemaleVoice || pickFemaleVoice();
    if (voice) utter.voice = voice;
    utter.rate = 1.0;
    utter.pitch = 1.1;
    window.speechSynthesis.speak(utter);
  } catch (err) {
    console.warn("Speech synthesis unavailable:", err);
  }
}

function addLog(text, type = "plain") {
  const line = document.createElement("div");
  line.className = "log-line";
  const t = document.createElement("span");
  t.className = "log-time";
  t.textContent = `+${elapsed()}s`;
  const msg = document.createElement("span");
  msg.className = `log-text ${type}`;
  msg.textContent = text;
  line.appendChild(t);
  line.appendChild(msg);
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
  speak(text);
}

function setStatus(text, cls) {
  statusBadge.textContent = text;
  statusBadge.className = `status-badge ${cls}`;
}

function clearStagedTimers() {
  stagedTimers.forEach((id) => clearTimeout(id));
  stagedTimers = [];
}

// Resolves once `seconds` have elapsed since startTime (or immediately if
// that time has already passed) — used to pace the 20s/25s/30s reveals.
function waitUntil(seconds) {
  return new Promise((resolve) => {
    const remaining = startTime + seconds * 1000 - Date.now();
    const id = setTimeout(resolve, Math.max(0, remaining));
    stagedTimers.push(id);
  });
}

function resetUI() {
  sosActive = false;
  cancelled = false;
  clearStagedTimers();
  sosBtn.classList.remove("confirming", "locating", "sent");
  sosBtnText.textContent = "SOS";
  sosBtnSub.textContent = "tap to trigger";
  cancelBtn.classList.add("hidden");
  manualLocationBox.classList.add("hidden");
  callBtn.classList.remove("emphasize");
  setStatus("Idle", "idle");
  stopRingAnimation(0, null);
}

// --- "SEE HOW IT WORKS" toggle ---
howBtn.addEventListener("click", () => {
  howPanel.classList.toggle("hidden");
});

// --- "OPEN DEMO" quick-fill: handy for laptop demos without GPS ---
demoBtn.addEventListener("click", () => {
  patientNameInput.value = "Demo Driver";
  manualToggle.checked = true;
  manualUpfrontBox.classList.remove("hidden");
  manualLatUpfront.value = "12.212722";
  manualLonUpfront.value = "79.070480";
  addLog("Demo data pre-filled (manual location enabled). Tap SOS to test.", "plain");
});

// --- Call Ambulance (108): always visible and clickable — an emergency
// call button should never be hidden for "reveal" effect. At the 5s
// checkpoint it gets a brief emphasis animation instead (see runSOSFlow).
callBtn.addEventListener("click", () => {
  window.location.href = "tel:108";
});

// --- Cancel alert within the grace window ---
cancelBtn.addEventListener("click", () => {
  if (!sosActive) return;
  cancelled = true;
  clearTimeout(cancelTimer);
  clearStagedTimers();
  addLog("Alert cancelled by user. Marked as OK.", "warn");
  setStatus("Cancelled", "cancelled");
  cancelBtn.classList.add("hidden");
  callBtn.classList.remove("emphasize");
  sosBtn.classList.remove("confirming", "locating");
  sosBtnText.textContent = "SOS";
  sosBtnSub.textContent = "tap to trigger";
  sosActive = false;
  stopRingAnimation(0, null);
});

// --- Trigger SOS ---
sosBtn.addEventListener("click", () => {
  if (sosActive) return;

  errorBox.classList.add("hidden");
  manualLocationBox.classList.add("hidden");
  logEl.innerHTML = "";
  startTime = Date.now();
  sosActive = true;
  cancelled = false;

  sosBtn.classList.add("confirming");
  sosBtnText.textContent = "SOS";
  sosBtnSub.textContent = "CONFIRMING";
  cancelBtn.classList.remove("hidden");
  setStatus("Countdown — tap cancel if safe", "confirming");

  addLog(`SOS triggered. ${CANCEL_WINDOW_SECONDS}s window to cancel.`, "warn");

  setRingProgress(0, "confirming");
  startRingAnimation();

  // +5s checkpoint: emphasize the Call Ambulance button (stays visible and
  // clickable throughout — this only adds a brief attention-drawing pulse)
  waitUntil(CALL_EMPHASIZE_AT).then(() => {
    if (cancelled) return;
    callBtn.classList.add("emphasize");
    setTimeout(() => callBtn.classList.remove("emphasize"), 1800);
  });

  cancelTimer = setTimeout(() => {
    if (cancelled) return;
    sosBtn.classList.remove("confirming");
    sosBtn.classList.add("locating");
    sosBtnText.textContent = "SOS";
    sosBtnSub.textContent = "LOCATING";
    runSOSFlow();
  }, CANCEL_WINDOW_SECONDS * 1000);
});

// --- Get device location, falling back to manual entry if it fails ---
function getLocation() {
  return new Promise((resolve, reject) => {
    // If the user pre-checked "No GPS on this device", skip the GPS
    // request entirely and use the manually entered coordinates right away.
    if (manualToggle.checked) {
      const lat = parseFloat(manualLatUpfront.value);
      const lon = parseFloat(manualLonUpfront.value);
      if (isNaN(lat) || isNaN(lon)) {
        showError("Please enter valid latitude and longitude in the manual location fields.");
        reject(new Error("invalid manual coords"));
        return;
      }
      resolve({ lat, lon });
      return;
    }

    if (!navigator.geolocation) {
      showManualLocationFallback();
      pendingManualResolve = resolve;
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
      (err) => {
        console.warn("Geolocation failed:", err);
        showManualLocationFallback();
        pendingManualResolve = resolve;
      },
      { enableHighAccuracy: true, timeout: 20000 }
    );
  });
}

function showManualLocationFallback() {
  manualLocationBox.classList.remove("hidden");
  addLog("Device GPS unavailable — enter coordinates manually below.", "warn");
}

useManualBtn.addEventListener("click", () => {
  const lat = parseFloat(manualLat.value);
  const lon = parseFloat(manualLon.value);

  if (isNaN(lat) || isNaN(lon)) {
    showError("Please enter valid latitude and longitude numbers.");
    return;
  }

  manualLocationBox.classList.add("hidden");

  if (pendingManualResolve) {
    pendingManualResolve({ lat, lon });
    pendingManualResolve = null;
  }
});

async function runSOSFlow() {
  const patientName = (patientNameInput.value || "Unknown Patient").trim();

  setStatus("Location captured — notifying", "locating");

  let loc;
  try {
    loc = await getLocation();
  } catch (err) {
    showError("Could not determine location.");
    resetUI();
    return;
  }

  addLog(`GPS location captured: ${loc.lat.toFixed(5)}°N, ${loc.lon.toFixed(5)}°E`, "info");

  // Fire the real request immediately (so hospital + contacts get notified
  // as fast as possible) — the *display* of the result is paced to the
  // 20s/25s checkpoints below, independent of how fast the network is.
  const backendPromise = fetch("/api/sos", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      patient_name: patientName,
      latitude: loc.lat,
      longitude: loc.lon,
    }),
  })
    .then(async (res) => {
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Something went wrong.");
      return data;
    });

  let data;
  try {
    // +20s checkpoint: reveal "nearest hospital identified"
    await waitUntil(HOSPITAL_REVEAL_AT);
    if (cancelled) return;
    data = await backendPromise; // resolves instantly if already done, or waits if slow
    addLog(`Nearest hospital identified: ${data.nearest_hospital.name} (${data.nearest_hospital.distance_km} km)`, "info");

    // +25s checkpoint: reveal "notifying emergency contacts"
    await waitUntil(NOTIFY_REVEAL_AT);
    if (cancelled) return;
    addLog(`Notifying ${data.contacts_notified} emergency contact(s) + hospital... (${data.emails_queued} alerts queued)`, "plain");

    // +30s checkpoint: fully sent
    await waitUntil(ESCALATION_WINDOW_SECONDS);
    if (cancelled) return;

    sosBtn.classList.remove("locating");
    sosBtn.classList.add("sent");
    sosBtnText.textContent = "SOS";
    sosBtnSub.textContent = "SENT";
    cancelBtn.classList.add("hidden");
    setStatus("Alert sent", "sent");
    sosActive = false;
    stopRingAnimation(1, "sent");
  } catch (err) {
    showError(err.message || "Could not reach the server. Is the Flask backend running?");
    console.error(err);
    resetUI();
  }
}

function showError(msg) {
  errorBox.textContent = "⚠️ " + msg;
  errorBox.classList.remove("hidden");
}
