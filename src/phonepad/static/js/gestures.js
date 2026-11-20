// Touchpad gesture recognition. Pure: fed with touch lists and timestamps, returns actions.
// No timers and no DOM, so it is unit-tested in tests/js/gestures.test.js.
//
// Actions:
//   { type: "move", dx, dy, dt }     one finger moved (CSS px, ms since last move)
//   { type: "scroll", dx, dy }       two fingers moved (average, CSS px, screen direction)
//   { type: "button", button, action }  action: "click" | "down" | "up"

export const DEFAULTS = Object.freeze({
  tapMaxMs: 250, // longest touch that still counts as a tap
  slop: 6, // CSS px a tap may wander; movement below it is not sent
  dragWindowMs: 250, // touch again this soon after a tap to drag
  tapDrag: true,
});

/** @typedef {{ id: number, x: number, y: number }} Touch */

export class GestureRecognizer {
  constructor(options = {}) {
    this.options = { ...DEFAULTS, ...options };
    /** @type {Map<number, {x: number, y: number}>} */
    this.touches = new Map();
    this.gesture = null;
    this.lastTapEnd = Number.NEGATIVE_INFINITY;
  }

  /** Fingers touched down. `touches`: all fingers now on the pad. */
  start(touches, t) {
    const actions = [];
    const o = this.options;
    if (this.gesture === null) {
      this.gesture = {
        start: t,
        lastMove: t,
        maxTouches: 0,
        moved: false,
        drag: false,
        travelX: 0,
        travelY: 0,
      };
      if (o.tapDrag && touches.length === 1 && t - this.lastTapEnd <= o.dragWindowMs) {
        this.gesture.drag = true;
        actions.push({ type: "button", button: "left", action: "down" });
      }
    }
    for (const touch of touches) {
      if (!this.touches.has(touch.id)) this.touches.set(touch.id, { x: touch.x, y: touch.y });
    }
    this.gesture.maxTouches = Math.max(this.gesture.maxTouches, this.touches.size);
    return actions;
  }

  /** Fingers moved. `touches`: all fingers now on the pad. */
  move(touches, t) {
    const g = this.gesture;
    if (g === null) return [];
    let sumX = 0;
    let sumY = 0;
    let count = 0;
    for (const touch of touches) {
      const last = this.touches.get(touch.id);
      if (!last) continue;
      sumX += touch.x - last.x;
      sumY += touch.y - last.y;
      count += 1;
      last.x = touch.x;
      last.y = touch.y;
    }
    const dt = t - g.lastMove;
    g.lastMove = t;
    if (count === 0) return [];

    const fingers = this.touches.size;
    let kind = null;
    if (g.maxTouches === 1 && fingers === 1) kind = "move";
    else if (g.maxTouches === 2 && fingers === 2) kind = "scroll";
    if (kind === null) return []; // fingers were lifted or 3+: ignore until all are up

    const dx = sumX / count;
    const dy = sumY / count;
    if (!g.moved) {
      g.travelX += dx;
      g.travelY += dy;
      if (Math.hypot(g.travelX, g.travelY) <= this.options.slop) return [];
      g.moved = true;
      return []; // movement inside the slop is dropped so taps never nudge the pointer
    }
    return kind === "move" ? [{ type: "move", dx, dy, dt }] : [{ type: "scroll", dx, dy }];
  }

  /** Fingers lifted. `touches`: the fingers still on the pad. */
  end(touches, t) {
    return this.#lift(touches, t, false);
  }

  /** The system took the touches away (incoming call, gesture navigation, ...). */
  cancel(t) {
    return this.#lift([], t, true);
  }

  #lift(touches, t, cancelled) {
    const g = this.gesture;
    if (g === null) return [];
    const remaining = new Set(touches.map((touch) => touch.id));
    for (const id of [...this.touches.keys()]) {
      if (!remaining.has(id)) this.touches.delete(id);
    }
    if (this.touches.size > 0) return [];

    this.gesture = null;
    const isTap = !cancelled && !g.moved && t - g.start <= this.options.tapMaxMs;
    if (g.drag) {
      // Down was sent when the touch began: a short touch turns it into a (double) click.
      if (isTap) this.lastTapEnd = t;
      return [{ type: "button", button: "left", action: "up" }];
    }
    if (!isTap) return [];
    if (g.maxTouches === 1) {
      this.lastTapEnd = t;
      return [{ type: "button", button: "left", action: "click" }];
    }
    if (g.maxTouches === 2) return [{ type: "button", button: "right", action: "click" }];
    return [];
  }
}
