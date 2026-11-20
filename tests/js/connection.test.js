import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import {
  CONNECT_TIMEOUT_MS,
  Connection,
  PING_INTERVAL_MS,
  PONG_TIMEOUT_MS,
} from "../../src/phonepad/static/js/connection.js";

/** Manual timers: `run(ms)` fires what is due after advancing the clock. */
function fakeTimers() {
  let now = 0;
  let next = 1;
  const pending = new Map();
  return {
    setTimeout(fn, ms) {
      const id = next++;
      pending.set(id, { at: now + ms, fn });
      return id;
    },
    clearTimeout(id) {
      pending.delete(id);
    },
    run(ms) {
      now += ms;
      for (const [id, t] of [...pending].sort((a, b) => a[1].at - b[1].at)) {
        if (t.at <= now && pending.has(id)) {
          pending.delete(id);
          t.fn();
        }
      }
    },
  };
}

class FakeSocket extends EventTarget {
  static CONNECTING = 0;
  static OPEN = 1;
  static instances = [];
  constructor(url) {
    super();
    this.url = url;
    this.readyState = FakeSocket.CONNECTING;
    this.sent = [];
    FakeSocket.instances.push(this);
  }
  send(data) {
    this.sent.push(JSON.parse(data));
  }
  close(code = 1000) {
    this.readyState = 3;
    this.dispatchEvent(Object.assign(new Event("close"), { code }));
  }
  open() {
    this.readyState = FakeSocket.OPEN;
    this.dispatchEvent(new Event("open"));
  }
  receive(message) {
    this.dispatchEvent(Object.assign(new Event("message"), { data: JSON.stringify(message) }));
  }
}

function memoryTokens(initial = null) {
  let token = initial;
  return { get: () => token, set: (t) => (token = t), clear: () => (token = null) };
}

let savedSocket;
beforeEach(() => {
  savedSocket = globalThis.WebSocket;
  globalThis.WebSocket = FakeSocket;
  FakeSocket.instances = [];
});
afterEach(() => {
  globalThis.WebSocket = savedSocket;
});

function statuses(conn) {
  const seen = [];
  conn.addEventListener("status", (e) => seen.push(e.detail.status));
  return seen;
}

test("without a token it asks for pairing and does not connect", () => {
  const conn = new Connection("ws://x/ws", memoryTokens(), "iPhone");
  const seen = statuses(conn);
  conn.connect();
  assert.deepEqual(seen, ["unpaired"]);
  assert.equal(FakeSocket.instances.length, 0);
});

test("pairing stores the token and becomes ready", () => {
  const tokens = memoryTokens();
  const conn = new Connection("ws://x/ws", tokens, "iPhone");
  const seen = statuses(conn);
  conn.pair("123 456");
  const ws = FakeSocket.instances[0];
  ws.open();
  assert.deepEqual(ws.sent, [{ type: "pair", v: 1, code: "123456", name: "iPhone", replaces: "" }]);
  ws.receive({ type: "paired", token: "secret", device: { id: "d", name: "iPhone" } });
  ws.receive({ type: "welcome", v: 1, server_version: "0.1.0", capabilities: ["pointer"] });
  assert.equal(tokens.get(), "secret");
  assert.equal(conn.status, "ready");
  assert.deepEqual(conn.capabilities, ["pointer"]);
  assert.ok(seen.includes("ready"));
  assert.ok(conn.send({ type: "move", dx: 1, dy: 0 }));
  assert.deepEqual(ws.sent.at(-1), { type: "move", dx: 1, dy: 0 });
});

test("a rejected token is forgotten and not retried", () => {
  const tokens = memoryTokens("old");
  const conn = new Connection("ws://x/ws", tokens, "iPhone");
  conn.connect();
  const ws = FakeSocket.instances[0];
  ws.open();
  assert.deepEqual(ws.sent, [{ type: "hello", v: 1, token: "old" }]);
  ws.receive({ type: "error", code: "unauthorized", message: "no" });
  ws.close(4401);
  assert.equal(tokens.get(), null);
  assert.equal(conn.status, "unpaired");
  assert.equal(conn.retryTimer, null);
});

test("a wrong pairing code reports an error", () => {
  const conn = new Connection("ws://x/ws", memoryTokens(), "iPhone");
  let error = null;
  conn.addEventListener("pairerror", (e) => {
    error = e.detail.message;
  });
  conn.pair("000000");
  const ws = FakeSocket.instances[0];
  ws.open();
  ws.receive({ type: "error", code: "bad_code", message: "Wrong code" });
  assert.equal(error, "Wrong code");
  assert.equal(conn.status, "unpaired");
});

test("a dropped connection is retried", () => {
  const conn = new Connection("ws://x/ws", memoryTokens("t"), "iPhone");
  conn.connect();
  const ws = FakeSocket.instances[0];
  ws.open();
  ws.receive({ type: "welcome", v: 1, capabilities: [] });
  ws.close(1006);
  assert.equal(conn.status, "offline");
  assert.notEqual(conn.retryTimer, null);
  assert.equal(conn.send({ type: "move", dx: 1, dy: 1 }), false);
  conn.disconnect(); // clears the timer so the test ends
});

test("re-pairing keeps the old token until the new code works", () => {
  const tokens = memoryTokens("old");
  const timers = fakeTimers();
  const conn = new Connection("ws://x/ws", tokens, "iPhone", timers);
  conn.pair("000000");
  const ws = FakeSocket.instances[0];
  ws.open();
  assert.equal(ws.sent[0].replaces, "old");
  ws.receive({ type: "error", code: "bad_code", message: "Wrong code" });
  assert.equal(tokens.get(), "old");
  timers.run(1000); // reconnects with the old token
  const next = FakeSocket.instances.at(-1);
  next.open();
  assert.deepEqual(next.sent, [{ type: "hello", v: 1, token: "old" }]);
});

test("a missing pong drops the socket and reconnects", () => {
  const timers = fakeTimers();
  const conn = new Connection("ws://x/ws", memoryTokens("t"), "iPhone", timers);
  conn.connect();
  const ws = FakeSocket.instances[0];
  ws.open();
  ws.receive({ type: "welcome", v: 1, capabilities: ["ping"] });
  timers.run(PING_INTERVAL_MS);
  assert.deepEqual(ws.sent.at(-1), { type: "ping" });
  ws.receive({ type: "pong" }); // answered: stays
  assert.equal(conn.status, "ready");
  timers.run(PING_INTERVAL_MS);
  timers.run(PONG_TIMEOUT_MS); // not answered: dead
  assert.equal(conn.status, "offline");
  timers.run(1000);
  assert.equal(FakeSocket.instances.length, 2);
  conn.disconnect();
});

test("a socket stuck connecting is abandoned", () => {
  const timers = fakeTimers();
  const conn = new Connection("ws://x/ws", memoryTokens("t"), "iPhone", timers);
  conn.connect();
  timers.run(CONNECT_TIMEOUT_MS);
  assert.equal(conn.status, "offline");
  timers.run(1000);
  assert.equal(FakeSocket.instances.length, 2);
  conn.disconnect();
});

test("reconnect replaces a socket that still looks open", () => {
  const conn = new Connection("ws://x/ws", memoryTokens("t"), "iPhone", fakeTimers());
  conn.connect();
  FakeSocket.instances[0].open();
  conn.reconnect();
  assert.equal(FakeSocket.instances.length, 2);
  conn.disconnect();
});

test("a bad-message close (4400) is retried", () => {
  const timers = fakeTimers();
  const conn = new Connection("ws://x/ws", memoryTokens("t"), "iPhone", timers);
  conn.connect();
  const ws = FakeSocket.instances[0];
  ws.open();
  ws.receive({ type: "welcome", v: 1, capabilities: [] });
  ws.close(4400);
  timers.run(1000);
  assert.equal(FakeSocket.instances.length, 2);
  conn.disconnect();
});
