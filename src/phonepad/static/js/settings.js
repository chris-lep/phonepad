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

function read(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // private mode or blocked storage: keep working with in-memory values
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
