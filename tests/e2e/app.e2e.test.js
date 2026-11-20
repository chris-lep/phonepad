// End-to-end: real server (loopback only, input recorded to a file, temporary state dirs) and
// headless Chrome emulating phones (iPhone, Android) with touch. Needs Chrome (CHROME_PATH,
// default /usr/bin/google-chrome) and the Python package (PYTHON, default "python").
// Run: make e2e

import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, test } from "node:test";
import puppeteer, { KnownDevices } from "puppeteer-core";

const CHROME = process.env.CHROME_PATH ?? "/usr/bin/google-chrome";
const PYTHON = process.env.PYTHON ?? "python";
const skip = !existsSync(CHROME) && `Chrome not found at ${CHROME}`;

let dir;
let env;
let server;
let url;
let browser;
let page;
const recordFile = () => join(dir, "events.jsonl");

function events() {
  if (!existsSync(recordFile())) return [];
  return readFileSync(recordFile(), "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

async function until(predicate, what, timeout = 5000) {
  const deadline = Date.now() + timeout;
  for (;;) {
    const value = await predicate();
    if (value) return value;
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${what}`);
    await new Promise((r) => setTimeout(r, 50));
  }
}

function cli(...args) {
  return execFileSync(PYTHON, ["-m", "phonepad", ...args], { env, encoding: "utf8" });
}

function newPairingCode() {
  const m = /Pairing code: (\d{3}) (\d{3})/.exec(cli("pair"));
  assert.ok(m, "pair printed a code");
  return m[1] + m[2];
}

const statusText = () => page.$eval("#status-text", (el) => el.textContent);
const center = async (selector) => {
  const box = await (await page.$(selector)).boundingBox();
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
};

/** Start the server (input recorded, loopback only); resolves with its URL. */
function startServer(port) {
  server = spawn(
    PYTHON,
    ["-m", "phonepad", "serve", "--no-lan", "--port", String(port), "--record-input", recordFile()],
    { env },
  );
  const proc = server;
  return new Promise((resolve, reject) => {
    let log = "";
    proc.stderr.on("data", (chunk) => {
      log += chunk;
      const m = /listening on (http:\/\/127\.0\.0\.1:\d+\/)/.exec(log);
      if (m) resolve(m[1]);
    });
    proc.on("exit", (code) => reject(new Error(`server exited (${code}): ${log}`)));
  });
}

function stopServer() {
  const proc = server;
  return new Promise((resolve) => {
    proc.on("exit", resolve);
    proc.kill();
  });
}

before(async () => {
  if (skip) return;
  dir = mkdtempSync(join(tmpdir(), "phonepad-e2e-"));
  env = {
    ...process.env,
    XDG_CONFIG_HOME: join(dir, "config"),
    XDG_STATE_HOME: join(dir, "state"),
  };
  url = await startServer(0);
  browser = await puppeteer.launch({ executablePath: CHROME, headless: true });
  page = await browser.newPage();
  await page.emulate(KnownDevices["iPhone 13"]);
  page.on("pageerror", (e) => assert.fail(`page error: ${e}`));
});

after(async () => {
  await browser?.close();
  server?.kill();
  if (dir) rmSync(dir, { recursive: true, force: true });
});

test("without pairing the pairing screen shows", { skip }, async () => {
  await page.goto(url);
  await page.waitForSelector("#pairing:not([hidden])");
  assert.equal(await statusText(), "Not paired");
});

test("a wrong code is rejected, the right one pairs", { skip }, async () => {
  const code = newPairingCode();
  const wrong = code === "000000" ? "111111" : "000000";
  await page.type("#pair-code", wrong);
  await page.click("#pair-form button");
  await until(
    () => page.$eval("#pair-error", (el) => el.textContent.includes("Wrong")),
    "pair error",
  );
  await page.type("#pair-code", code);
  await page.click("#pair-form button");
  await until(async () => (await statusText()) === "Connected", "connected");
  assert.equal(await page.$eval("#pairing", (el) => el.hidden), true);
});

test("QR link pairs and the code leaves the URL", { skip }, async () => {
  const deviceIds = () => [...cli("devices").matchAll(/^([0-9a-f]{8}) /gm)].map((m) => m[1]);
  const [oldId] = deviceIds();
  const code = newPairingCode();
  // Same page, only the fragment changes (QR scanned while the app is open).
  await page.goto(`${url}#code=${code}`);
  // The same phone pairs again: its old entry is replaced, not duplicated.
  await until(() => {
    const ids = deviceIds();
    return ids.length === 1 && ids[0] !== oldId;
  }, "device replaced");
  await until(async () => (await statusText()) === "Connected", "connected via link");
  assert.equal(new URL(page.url()).hash, "");
});

test("tap clicks, dragging a finger moves the pointer", { skip }, async () => {
  const before = events().length;
  const { x, y } = await center("#pad");
  await page.touchscreen.tap(x, y);
  await until(() => events().length >= before + 2, "click events");
  assert.deepEqual(events().slice(before, before + 2), [
    { kind: "button", button: "left", pressed: true },
    { kind: "button", button: "left", pressed: false },
  ]);

  await new Promise((r) => setTimeout(r, 400)); // outside the tap-and-drag window
  const start = events().length;
  const touch = await page.touchscreen.touchStart(x, y);
  for (let i = 1; i <= 10; i++) {
    await touch.move(x + i * 8, y + i * 4);
    await new Promise((r) => setTimeout(r, 16));
  }
  await touch.end();
  const moves = await until(() => {
    const m = events()
      .slice(start)
      .filter((e) => e.kind === "move");
    return m.length > 0 && m;
  }, "move events");
  const total = moves.reduce((acc, e) => ({ dx: acc.dx + e.dx, dy: acc.dy + e.dy }), {
    dx: 0,
    dy: 0,
  });
  assert.ok(total.dx > 0 && total.dy > 0, `moved right and down: ${JSON.stringify(total)}`);
  assert.ok(
    !events()
      .slice(start)
      .some((e) => e.kind === "button"),
    "no click after a move",
  );
});

test("L button holds until released", { skip }, async () => {
  const before = events().length;
  const { x, y } = await center('[data-button="left"]');
  await page.mouse.move(x, y);
  await page.mouse.down();
  await until(() => events().length > before, "button down");
  await page.mouse.up();
  await until(() => events().length > before + 1, "button up");
  assert.deepEqual(
    events()
      .slice(before)
      .map((e) => e.pressed),
    [true, false],
  );
});

test("typing is sent live, Enter and special keys work", { skip }, async () => {
  await page.click("#keyboard-toggle");
  await page.waitForSelector("#keyboard:not([hidden])");
  const before = events().length;
  await page.type("#type-field", "Hä");
  await page.keyboard.press("Backspace");
  await page.keyboard.press("Enter");
  await until(() => events().length >= before + 4, "Enter (sent after a short delay)");
  const { x, y } = await center('[data-key="tab"]');
  await page.mouse.click(x, y);
  await until(() => events().length >= before + 5, "typing events");
  assert.deepEqual(events().slice(before), [
    { kind: "text", text: "H" },
    { kind: "text", text: "ä" },
    { kind: "key", key: "backspace" },
    { kind: "key", key: "enter" },
    { kind: "key", key: "tab" },
  ]);
  assert.equal(await page.$eval("#type-field", (el) => el.value), "​");
});

test("text typed during an outage is not sent, and nothing leaks after reconnect", {
  skip,
}, async () => {
  const port = new URL(url).port;
  await stopServer();
  await until(async () => (await statusText()) !== "Connected", "noticed the outage");
  // The keyboard panel is still open from the previous test.
  await page.type("#type-field", "lost");
  assert.equal(await page.$eval("#type-field", (el) => el.value), "\u200b");
  assert.match(await page.$eval("#toast", (el) => el.textContent), /Not connected/);

  url = await startServer(port);
  await until(async () => (await statusText()) === "Connected", "reconnected", 10000);
  const before = events().length; // the restarted server truncated the record file
  await page.type("#type-field", "ok");
  await page.keyboard.press("Backspace");
  await until(() => events().length >= before + 3, "typing after reconnect");
  assert.deepEqual(events().slice(before), [
    { kind: "text", text: "o" },
    { kind: "text", text: "k" },
    { kind: "key", key: "backspace" },
  ]);
});

test("the token survives a reload", { skip }, async () => {
  await page.reload();
  await until(async () => (await statusText()) === "Connected", "reconnected");
});

test("revoking a device sends it back to pairing", { skip }, async () => {
  cli("revoke", "--all");
  await page.waitForSelector("#pairing:not([hidden])", { timeout: 8000 });
  assert.equal(await statusText(), "Not paired");
});

test("an Android phone (emulated) pairs and clicks", { skip }, async () => {
  const android = await browser.newPage();
  await android.emulate(KnownDevices["Pixel 5"]);
  android.on("pageerror", (e) => assert.fail(`page error: ${e}`));
  const code = newPairingCode();
  await android.goto(`${url}#code=${code}`);
  await until(
    () => android.$eval("#status-text", (el) => el.textContent === "Connected"),
    "Android connected",
  );
  assert.match(cli("devices"), /Android \(browser, /);
  const before = events().length;
  const box = await (await android.$("#pad")).boundingBox();
  await android.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
  await until(() => events().length >= before + 2, "click from Android");
  assert.deepEqual(
    events()
      .slice(before)
      .map((e) => e.pressed),
    [true, false],
  );
  await android.close();
});
