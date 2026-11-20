// Settings and the device token, kept in this page's local storage (per phone, per
// Safari / home-screen app). Storage may be unavailable or cleared: defaults then apply.

export const DEFAULT_SETTINGS = Object.freeze({
  speed: 1.6,
  acceleration: 1.2,
  scrollSpeed: 1,
  naturalScroll: true,
  tapDrag: true,
  autocorrect: true,
});

/** Slider ranges for the settings panel. */
export const RANGES = Object.freeze({
  speed: { min: 0.5, max: 4, step: 0.1 },
  acceleration: { min: 0, max: 3, step: 0.1 },
  scrollSpeed: { min: 0.25, max: 4, step: 0.25 },
});

const SETTINGS_KEY = "phonepad.settings";
const TOKEN_KEY = "phonepad.token";

// Fallback while storage is blocked (private mode): values live until the page is closed.
const memory = new Map();

function read(key) {
  try {
    const value = localStorage.getItem(key);
    if (value !== null) return value;
  } catch {
    // blocked storage
  }
  return memory.get(key) ?? null;
}

function write(key, value) {
  if (value === null) memory.delete(key);
  else memory.set(key, value);
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // blocked storage: the in-memory copy above keeps the page working
  }
}

/** Settings merged over the defaults; unknown or ill-typed values are dropped. */
export function loadSettings() {
  const result = { ...DEFAULT_SETTINGS };
  try {
    const stored = JSON.parse(read(SETTINGS_KEY) ?? "{}");
    for (const [key, value] of Object.entries(stored ?? {})) {
      if (key in DEFAULT_SETTINGS && typeof value === typeof DEFAULT_SETTINGS[key]) {
        result[key] = value;
      }
    }
  } catch {
    // corrupt JSON: defaults
  }
  return result;
}

export function saveSettings(settings) {
  write(SETTINGS_KEY, JSON.stringify(settings));
}

export const tokenStore = {
  get: () => read(TOKEN_KEY),
  set: (token) => write(TOKEN_KEY, token),
  clear: () => write(TOKEN_KEY, null),
};
