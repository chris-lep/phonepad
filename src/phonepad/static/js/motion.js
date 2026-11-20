// Pointer acceleration, scroll conversion and per-frame batching. Pure apart from the
// injected scheduler, unit-tested in tests/js/motion.test.js.

export const WHEEL_NOTCH = 120;
// Per-message limits of the protocol (phonepad/protocol.py MAX_MOVE, MAX_SCROLL).
export const MAX_MOVE = 2000;
export const MAX_SCROLL = 120 * 50;
const UNITS_PER_PX = 3; // wheel units per CSS px of finger travel at scroll speed 1

/**
 * Pointer gain for a finger speed `v` in CSS px per ms (see docs/SPEC.md, "Touchpad").
 * @param {number} v
 * @param {{ speed: number, acceleration: number }} settings
 */
export function pointerGain(v, { speed, acceleration }) {
  return speed * (1 + acceleration * Math.min(Math.max(v - 0.1, 0), 1.5));
}

/** Pointer delta (float) for a finger move of dx, dy over dt ms. */
export function accelerate(dx, dy, dt, settings) {
  const v = Math.hypot(dx, dy) / Math.max(dt, 4);
  const gain = pointerGain(v, settings);
  return { dx: dx * gain, dy: dy * gain };
}

/**
 * Wheel units (protocol signs: dy > 0 scrolls up, dx > 0 scrolls right) for a two-finger move
 * of dx, dy CSS px in screen direction.
 */
export function scrollUnits(dx, dy, { scrollSpeed, naturalScroll }) {
  const k = UNITS_PER_PX * scrollSpeed;
  // Natural: content follows the fingers. Fingers down => content down => view moves up.
  const sign = naturalScroll ? 1 : -1;
  return { dx: -dx * k * sign, dy: dy * k * sign };
}

/** Sums float deltas and hands out whole numbers, keeping the remainder. */
export class Accumulator {
  constructor() {
    this.x = 0;
    this.y = 0;
  }

  add(dx, dy) {
    this.x += dx;
    this.y += dy;
  }

  /** Whole parts (truncated towards zero); the fractions stay for next time. */
  take() {
    const dx = Math.trunc(this.x) || 0; // no -0
    const dy = Math.trunc(this.y) || 0;
    this.x -= dx;
    this.y -= dy;
    return { dx, dy };
  }
}

/** Split a delta into pieces within ±limit per axis (empty for no movement). */
export function split({ dx, dy }, limit) {
  const parts = [];
  while (dx || dy) {
    const px = Math.max(-limit, Math.min(limit, dx));
    const py = Math.max(-limit, Math.min(limit, dy));
    parts.push({ dx: px, dy: py });
    dx -= px;
    dy -= py;
  }
  return parts;
}

/**
 * Collects pointer and scroll movement and sends it at most once per frame.
 * `send(message)` gets protocol messages; `schedule(fn)` defaults to requestAnimationFrame.
 */
export class FrameBatcher {
  constructor(send, schedule = (fn) => requestAnimationFrame(fn)) {
    this.send = send;
    this.schedule = schedule;
    this.move = new Accumulator();
    this.scroll = new Accumulator();
    this.pending = false;
  }

  addMove(dx, dy) {
    this.move.add(dx, dy);
    this.#request();
  }

  addScroll(dx, dy) {
    this.scroll.add(dx, dy);
    this.#request();
  }

  #request() {
    if (this.pending) return;
    this.pending = true;
    this.schedule(() => this.flush());
  }

  /** Send what has collected now (also call before clicks and keys to keep the order). */
  flush() {
    this.pending = false;
    for (const part of split(this.move.take(), MAX_MOVE)) this.send({ type: "move", ...part });
    for (const part of split(this.scroll.take(), MAX_SCROLL)) {
      this.send({ type: "scroll", ...part });
    }
  }

  /** Drop collected movement (e.g. when the connection is lost). */
  reset() {
    this.move = new Accumulator();
    this.scroll = new Accumulator();
  }
}
