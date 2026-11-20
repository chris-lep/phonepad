import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { GestureRecognizer } from "../../src/phonepad/static/js/gestures.js";

const one = (x, y, id = 1) => [{ id, x, y }];
const two = (x1, y1, x2, y2) => [
  { id: 1, x: x1, y: y1 },
  { id: 2, x: x2, y: y2 },
];
const click = (button) => ({ type: "button", button, action: "click" });
const down = { type: "button", button: "left", action: "down" };
const up = { type: "button", button: "left", action: "up" };

describe("one finger", () => {
  test("a short touch is a left click", () => {
    const g = new GestureRecognizer();
    assert.deepEqual(g.start(one(10, 10), 0), []);
    assert.deepEqual(g.move(one(12, 11), 50), []); // inside the slop
    assert.deepEqual(g.end([], 120), [click("left")]);
  });

  test("a long touch without movement is not a click", () => {
    const g = new GestureRecognizer();
    g.start(one(10, 10), 0);
    assert.deepEqual(g.end([], 400), []);
  });

  test("movement beyond the slop moves the pointer, without the slop itself", () => {
    const g = new GestureRecognizer();
    g.start(one(0, 0), 0);
    assert.deepEqual(g.move(one(4, 0), 10), []);
    assert.deepEqual(g.move(one(8, 0), 20), []); // crosses the slop: dropped
    assert.deepEqual(g.move(one(18, 5), 36), [{ type: "move", dx: 10, dy: 5, dt: 16 }]);
    assert.deepEqual(g.end([], 60), []); // moved: no click
  });
});

describe("tap and drag", () => {
  test("tap, then touch again soon and move: drag", () => {
    const g = new GestureRecognizer();
    g.start(one(0, 0), 0);
    assert.deepEqual(g.end([], 100), [click("left")]);
    assert.deepEqual(g.start(one(0, 0, 2), 250), [down]);
    g.move(one(20, 0, 2), 270);
    assert.deepEqual(g.move(one(30, 0, 2), 286), [{ type: "move", dx: 10, dy: 0, dt: 16 }]);
    assert.deepEqual(g.end([], 600), [up]);
  });

  test("a quick second tap is down + up (double click), a third continues", () => {
    const g = new GestureRecognizer();
    g.start(one(0, 0), 0);
    g.end([], 80);
    assert.deepEqual(g.start(one(0, 0), 200), [down]);
    assert.deepEqual(g.end([], 260), [up]);
    assert.deepEqual(g.start(one(0, 0), 400), [down]);
    assert.deepEqual(g.end([], 450), [up]);
  });

  test("touching again too late is a new gesture", () => {
    const g = new GestureRecognizer();
    g.start(one(0, 0), 0);
    g.end([], 80);
    assert.deepEqual(g.start(one(0, 0), 400), []);
  });

  test("can be switched off", () => {
    const g = new GestureRecognizer({ tapDrag: false });
    g.start(one(0, 0), 0);
    g.end([], 80);
    assert.deepEqual(g.start(one(0, 0), 150), []);
    assert.deepEqual(g.end([], 200), [click("left")]);
  });

  test("cancel releases the button", () => {
    const g = new GestureRecognizer();
    g.start(one(0, 0), 0);
    g.end([], 80);
    g.start(one(0, 0), 150);
    assert.deepEqual(g.cancel(300), [up]);
  });
});

describe("two fingers", () => {
  test("a short two-finger touch is a right click", () => {
    const g = new GestureRecognizer();
    g.start(one(0, 0), 0);
    g.start(two(0, 0, 40, 0), 20);
    assert.deepEqual(g.end(one(0, 0), 100), []);
    assert.deepEqual(g.end([], 110), [click("right")]);
  });

  test("moving two fingers scrolls by their average", () => {
    const g = new GestureRecognizer();
    g.start(two(0, 0, 40, 0), 0);
    g.move(two(0, 10, 40, 10), 16); // crosses the slop
    assert.deepEqual(g.move(two(0, 30, 40, 20), 32), [{ type: "scroll", dx: 0, dy: 15 }]);
    assert.deepEqual(g.end([], 100), []);
  });

  test("after lifting one finger the other does not move the pointer", () => {
    const g = new GestureRecognizer();
    g.start(two(0, 0, 40, 0), 0);
    g.end(one(0, 0), 50);
    assert.deepEqual(g.move(one(50, 50), 70), []);
    assert.deepEqual(g.end([], 300), []);
  });

  test("three fingers do nothing", () => {
    const g = new GestureRecognizer();
    g.start([...two(0, 0, 20, 0), { id: 3, x: 40, y: 0 }], 0);
    assert.deepEqual(g.move([...two(0, 50, 20, 50), { id: 3, x: 40, y: 50 }], 20), []);
    assert.deepEqual(g.end([], 100), []);
  });
});
