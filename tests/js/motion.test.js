import assert from "node:assert/strict";
import { test } from "node:test";
import {
  Accumulator,
  accelerate,
  FrameBatcher,
  pointerGain,
  scrollUnits,
} from "../../src/phonepad/static/js/motion.js";

test("gain: constant when slow, grows with speed, capped", () => {
  const s = { speed: 2, acceleration: 1 };
  assert.equal(pointerGain(0, s), 2);
  assert.equal(pointerGain(0.1, s), 2);
  assert.ok(pointerGain(1, s) > pointerGain(0.5, s));
  assert.equal(pointerGain(10, s), pointerGain(1.6, s));
  assert.equal(pointerGain(5, { speed: 1.5, acceleration: 0 }), 1.5);
});

test("accelerate scales both axes by the gain", () => {
  const d = accelerate(3, 4, 50, { speed: 2, acceleration: 0 });
  assert.deepEqual(d, { dx: 6, dy: 8 });
});

test("natural scrolling: content follows the fingers", () => {
  const natural = { scrollSpeed: 1, naturalScroll: true };
  // fingers move down => view moves up => wheel up (dy > 0)
  assert.ok(scrollUnits(0, 10, natural).dy > 0);
  // fingers move right => view moves left => wheel left (dx < 0)
  assert.ok(scrollUnits(10, 0, natural).dx < 0);
  const classic = { scrollSpeed: 1, naturalScroll: false };
  assert.ok(scrollUnits(0, 10, classic).dy < 0);
  assert.ok(scrollUnits(10, 0, classic).dx > 0);
});

test("accumulator keeps fractions", () => {
  const acc = new Accumulator();
  acc.add(0.6, -0.6);
  assert.deepEqual(acc.take(), { dx: 0, dy: 0 });
  acc.add(0.6, -0.6);
  const t = acc.take();
  assert.equal(t.dx, 1);
  assert.equal(t.dy, -1);
});

test("batcher sends once per frame and flushes on demand", () => {
  const sent = [];
  const frames = [];
  const b = new FrameBatcher(
    (m) => sent.push(m),
    (fn) => frames.push(fn),
  );
  b.addMove(1.5, 0);
  b.addMove(1.5, 2);
  b.addScroll(0, 120);
  assert.equal(frames.length, 1);
  frames[0]();
  assert.deepEqual(sent, [
    { type: "move", dx: 3, dy: 2 },
    { type: "scroll", dx: 0, dy: 120 },
  ]);
  b.addMove(0.4, 0);
  b.flush();
  assert.equal(sent.length, 2); // nothing whole to send yet
});
