// DOM wiring: touchpad, buttons, keyboard panel, pairing and settings sheets.
// Logic lives in the pure modules (gestures, motion, typing) and is unit-tested there.

import { Connection } from "./connection.js";
import { GestureRecognizer } from "./gestures.js";
import { accelerate, FrameBatcher, scrollUnits } from "./motion.js";
import { loadSettings, RANGES, saveSettings, tokenStore } from "./settings.js";
import { chunkEdit, TypingBuffer } from "./typing.js";

const $ = (id) => document.getElementById(id);

const settings = loadSettings();
const connection = new Connection(webSocketUrl(), tokenStore, deviceName());
const batcher = new FrameBatcher((message) => connection.send(message));
const gestures = new GestureRecognizer({ tapDrag: settings.tapDrag });
const typing = new TypingBuffer();

function webSocketUrl() {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}/ws`;
}

function deviceName() {
  const ua = navigator.userAgent;
  const kind = /iPhone/.test(ua)
    ? "iPhone"
    : /iPad/.test(ua)
      ? "iPad"
      : /Android/.test(ua)
        ? "Android"
        : "Browser";
  const mode = matchMedia("(display-mode: standalone)").matches ? "app" : "browser";
  return `${kind} (${mode}, ${new Date().toISOString().slice(0, 10)})`;
}

/** Send a discrete message after any pending movement, so the order is kept. */
function sendNow(message) {
  batcher.flush();
  return connection.send(message);
}

// --- touchpad --------------------------------------------------------------------------------

const pad = $("pad");

function touchList(list) {
  return Array.from(list, (t) => ({ id: t.identifier, x: t.clientX, y: t.clientY }));
}

function apply(actions) {
  for (const action of actions) {
    if (action.type === "move") {
      const d = accelerate(action.dx, action.dy, action.dt, settings);
      batcher.addMove(d.dx, d.dy);
    } else if (action.type === "scroll") {
      const u = scrollUnits(action.dx, action.dy, settings);
      batcher.addScroll(u.dx, u.dy);
    } else if (action.type === "button") {
      sendNow({ type: "button", button: action.button, action: action.action });
      resetTyping(); // a click may move the laptop's text cursor
    }
  }
}

const touchOptions = { passive: false };
pad.addEventListener(
  "touchstart",
  (e) => {
    e.preventDefault(); // no emulated mouse events, no focus change (keyboard stays open)
    $("pad-hint").classList.add("faded");
    apply(gestures.start(touchList(e.targetTouches), e.timeStamp));
  },
  touchOptions,
);
pad.addEventListener(
  "touchmove",
  (e) => {
    e.preventDefault();
    apply(gestures.move(touchList(e.targetTouches), e.timeStamp));
  },
  touchOptions,
);
pad.addEventListener(
  "touchend",
  (e) => {
    e.preventDefault();
    apply(gestures.end(touchList(e.targetTouches), e.timeStamp));
  },
  touchOptions,
);
pad.addEventListener("touchcancel", (e) => apply(gestures.cancel(e.timeStamp)));

// --- L / R buttons ---------------------------------------------------------------------------

for (const el of document.querySelectorAll("[data-button]")) {
  const button = el.dataset.button;
  let held = false;
  const release = () => {
    if (!held) return;
    held = false;
    el.classList.remove("active");
    sendNow({ type: "button", button, action: "up" });
  };
  el.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    el.setPointerCapture(e.pointerId);
    held = true;
    el.classList.add("active");
    sendNow({ type: "button", button, action: "down" });
    resetTyping();
  });
  el.addEventListener("pointerup", release);
  el.addEventListener("pointercancel", release);
  el.addEventListener("lostpointercapture", release);
  el.addEventListener("contextmenu", (e) => e.preventDefault());
}

// --- keyboard panel --------------------------------------------------------------------------

const keyboard = $("keyboard");
const field = $("type-field");
const keyboardToggle = $("keyboard-toggle");

function resetTyping() {
  typing.reset();
  field.value = typing.emptyField;
}

function placeCaretAtEnd() {
  const end = field.value.length;
  field.setSelectionRange(end, end);
}

function setKeyboardOpen(open) {
  keyboard.hidden = !open;
  $("buttons").hidden = open;
  keyboardToggle.setAttribute("aria-pressed", String(open));
  if (open) {
    resetTyping();
    field.focus(); // must run inside the tap handler, or iOS will not show the keyboard
    placeCaretAtEnd();
  } else {
    field.blur();
  }
}

keyboardToggle.addEventListener("click", () => setKeyboardOpen(keyboard.hidden));

field.addEventListener("input", () => {
  if (!connection.ready) {
    // Never let the buffer believe text reached the laptop: later backspaces would delete
    // unrelated text there.
    resetTyping();
    showToast("Not connected: the text was not sent.");
    return;
  }
  const { edit, field: replacement } = typing.input(field.value);
  if (replacement !== null) {
    field.value = replacement;
    placeCaretAtEnd();
  }
  if (edit && !chunkEdit(edit).every((message) => sendNow(message))) resetTyping();
});

// A mobile keyboard (seen on iOS) may apply a pending autocorrection after the Return keydown; give its input event a
// moment to arrive before Enter goes out and the field is cleared.
const ENTER_DELAY_MS = 50;
field.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.isComposing) {
    setTimeout(() => {
      sendNow({ type: "key", key: "enter" });
      resetTyping();
    }, ENTER_DELAY_MS);
  }
});

field.addEventListener("focus", placeCaretAtEnd);

for (const el of document.querySelectorAll("[data-key]")) {
  el.addEventListener("pointerdown", (e) => {
    e.preventDefault(); // keep the focus (and the iOS keyboard) in the text field
    sendNow({ type: "key", key: el.dataset.key });
    resetTyping();
  });
}

function applyTypingSettings() {
  field.setAttribute("autocorrect", settings.autocorrect ? "on" : "off");
  field.setAttribute("autocapitalize", settings.autocorrect ? "sentences" : "off");
  field.spellcheck = settings.autocorrect;
}

// --- viewport (mobile keyboards shrink only the visual viewport on iOS) ----------------------------

const app = $("app");
function fitViewport() {
  const vv = window.visualViewport;
  const height = vv ? vv.height : window.innerHeight;
  document.documentElement.style.setProperty("--app-height", `${Math.round(height)}px`);
  app.style.transform = vv?.offsetTop ? `translateY(${vv.offsetTop}px)` : "";
}
window.visualViewport?.addEventListener("resize", fitViewport);
window.visualViewport?.addEventListener("scroll", fitViewport);
window.addEventListener("resize", fitViewport);
document.addEventListener("gesturestart", (e) => e.preventDefault()); // no page zoom
fitViewport();

// --- connection status -----------------------------------------------------------------------

const STATUS_TEXT = {
  connecting: "Connecting…",
  ready: "Connected",
  offline: "Offline · tap to retry",
  unpaired: "Not paired",
};

connection.addEventListener("status", (e) => {
  const { status, capabilities } = e.detail;
  $("status").dataset.status = status;
  $("status-text").textContent = STATUS_TEXT[status] ?? status;
  app.classList.toggle("inactive", status !== "ready");
  keyboardToggle.disabled = status === "ready" && !capabilities.includes("keyboard");
  $("pairing").hidden = status !== "unpaired";
  if (status !== "ready") batcher.reset();
  resetTyping(); // the laptop's text cursor may have moved while we were away
  if (status === "ready") $("pair-error").textContent = "";
  $("about").textContent = connection.serverVersion
    ? `phonepad server ${connection.serverVersion}`
    : "";
});

connection.addEventListener("error", (e) => showToast(e.detail.message));
connection.addEventListener("pairerror", (e) => {
  $("pair-error").textContent = e.detail.message;
});

$("status").addEventListener("click", () => connection.reconnect());

// After the phone slept, the socket can look open while it is dead: start a fresh one.
const STALE_AFTER_MS = 3000;
let hiddenSince = null;
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") {
    hiddenSince = Date.now();
    return;
  }
  const stale = hiddenSince !== null && Date.now() - hiddenSince > STALE_AFTER_MS;
  hiddenSince = null;
  if (stale) connection.reconnect();
  else connection.connect();
});
for (const event of ["pageshow", "online"]) {
  window.addEventListener(event, () => connection.connect());
}

let toastTimer;
function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.hidden = true;
  }, 4000);
}

// --- pairing ---------------------------------------------------------------------------------

$("pair-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const code = $("pair-code").value.replace(/\D/g, "");
  if (code.length !== 6) {
    $("pair-error").textContent = "The code has 6 digits.";
    return;
  }
  $("pair-error").textContent = "";
  $("pair-code").value = "";
  $("pair-code").blur();
  connection.pair(code);
});

// --- settings --------------------------------------------------------------------------------

function formatSetting(key, value) {
  return key === "acceleration" ? value.toFixed(1) : `${value.toFixed(value < 1 ? 2 : 1)}×`;
}

for (const input of document.querySelectorAll("[data-setting]")) {
  const key = input.dataset.setting;
  const output = document.querySelector(`output[data-for="${key}"]`);
  if (input.type === "checkbox") {
    input.checked = settings[key];
  } else {
    Object.assign(input, RANGES[key]);
    input.value = String(settings[key]);
    output.textContent = formatSetting(key, settings[key]);
  }
  input.addEventListener("input", () => {
    settings[key] = input.type === "checkbox" ? input.checked : Number(input.value);
    if (output) output.textContent = formatSetting(key, settings[key]);
    gestures.options.tapDrag = settings.tapDrag;
    applyTypingSettings();
    saveSettings(settings);
  });
}

$("settings-toggle").addEventListener("click", () => {
  if (!keyboard.hidden) setKeyboardOpen(false);
  $("settings").hidden = false;
});
$("settings-close").addEventListener("click", () => {
  $("settings").hidden = true;
});
$("unpair").addEventListener("click", () => {
  if (!confirm("Unpair this phone? You will need a new code from `phonepad pair`.")) return;
  $("settings").hidden = true;
  connection.unpair();
});

// --- start -----------------------------------------------------------------------------------

applyTypingSettings();
resetTyping();

/** Pair with a code from the QR link (`#code=123456`); true if there was one. */
function pairFromLink() {
  const match = /(?:^#|&)code=(\d{6})/.exec(location.hash);
  if (!match) return false;
  history.replaceState(null, "", location.pathname); // keep the code out of history/bookmarks
  connection.pair(match[1]);
  return true;
}

window.addEventListener("hashchange", pairFromLink); // QR scanned while the page is open
if (!pairFromLink()) connection.connect();
