import assert from "node:assert/strict";
import { test } from "node:test";
import { diff, graphemes, SENTINEL, TypingBuffer } from "../../src/phonepad/static/js/typing.js";

test("diff keeps the common prefix", () => {
  assert.deepEqual(diff("", "hi"), { backspace: 0, insert: "hi" });
  assert.deepEqual(diff("hi", "hi!"), { backspace: 0, insert: "!" });
  assert.deepEqual(diff("teh", "the "), { backspace: 2, insert: "he " }); // autocorrect
  assert.deepEqual(diff("hello", "hllo"), { backspace: 4, insert: "llo" }); // edit in the middle
  assert.deepEqual(diff("abc", ""), { backspace: 3, insert: "" });
});

test("graphemes count emoji sequences as one character", () => {
  assert.deepEqual(graphemes("a👍🏽ö"), ["a", "👍🏽", "ö"]);
  assert.deepEqual(diff("ok👍🏽", "ok"), { backspace: 1, insert: "" });
});

test("buffer: typing, autocorrect and Backspace on an empty field", () => {
  const b = new TypingBuffer();
  assert.equal(b.emptyField, SENTINEL);
  assert.deepEqual(b.input(`${SENTINEL}H`), { edit: { backspace: 0, insert: "H" }, field: null });
  assert.deepEqual(b.input(`${SENTINEL}Hallo`).edit, { backspace: 0, insert: "allo" });
  assert.deepEqual(b.input(`${SENTINEL}Hallo `).edit, { backspace: 0, insert: " " });
  assert.equal(b.input(`${SENTINEL}Hallo `).edit, null); // no change
  assert.deepEqual(b.input(SENTINEL).edit, { backspace: 6, insert: "" }); // select all + delete
  // The marker itself deleted: Backspace on an empty field.
  assert.deepEqual(b.input(""), { edit: { backspace: 1, insert: "" }, field: SENTINEL });
});

test("buffer: marker lost while text is present restores it without extra keys", () => {
  const b = new TypingBuffer();
  b.input(`${SENTINEL}ab`);
  assert.deepEqual(b.input("ab"), { edit: null, field: `${SENTINEL}ab` });
});

test("buffer: select all + cut sends only the typed text's backspaces", () => {
  const b = new TypingBuffer();
  b.input(`${SENTINEL}abc`);
  assert.deepEqual(b.input(""), { edit: { backspace: 3, insert: "" }, field: SENTINEL });
});

test("buffer: reset forgets sent text", () => {
  const b = new TypingBuffer();
  b.input(`${SENTINEL}abc`);
  b.reset();
  assert.deepEqual(b.input(`${SENTINEL}x`).edit, { backspace: 0, insert: "x" });
});
