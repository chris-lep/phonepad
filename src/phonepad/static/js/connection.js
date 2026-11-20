// WebSocket connection to the laptop: authentication, pairing, liveness and reconnects.
//
// Events (CustomEvent, details in `event.detail`):
//   "status"  { status: "connecting" | "ready" | "offline" | "unpaired", capabilities }
//   "error"   { code, message }          server-reported problem (not fatal)
//   "pairerror" { message }              the pairing code was rejected

export const PROTOCOL_VERSION = 1;
const RETRY_MS = [500, 1000, 2000, 4000, 5000];
export const CONNECT_TIMEOUT_MS = 6000; // a socket stuck in CONNECTING is abandoned
export const PING_INTERVAL_MS = 10000;
export const PONG_TIMEOUT_MS = 4000; // no answer: the socket is dead (e.g. after phone sleep)

export class Connection extends EventTarget {
  /**
   * @param {string} url  WebSocket URL
   * @param {{ get(): string|null, set(t: string): void, clear(): void }} tokens
   * @param {string} deviceName  name sent when pairing
   * @param {{ setTimeout: Function, clearTimeout: Function }} timers  injectable for tests
   */
  constructor(url, tokens, deviceName, timers = globalThis) {
    super();
    this.url = url;
    this.tokens = tokens;
    this.deviceName = deviceName;
    this.timers = timers;
    this.ws = null;
    this.status = "offline";
    this.capabilities = [];
    this.serverVersion = "";
    this.pairCode = null;
    this.attempt = 0;
    this.retryTimer = null;
    this.connectTimer = null;
    this.pingTimer = null;
    this.pongTimer = null;
  }

  get ready() {
    return this.status === "ready";
  }

  /** Connect if paired (or a pairing code is pending) and not already connected. */
  connect() {
    this.#clear("retryTimer");
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) return;
    if (!this.tokens.get() && !this.pairCode) {
      this.#setStatus("unpaired");
      return;
    }
    this.#setStatus("connecting");
    const ws = new WebSocket(this.url);
    this.ws = ws;
    this.connectTimer = this.timers.setTimeout(() => {
      if (ws === this.ws && ws.readyState === WebSocket.CONNECTING) this.#drop(ws);
    }, CONNECT_TIMEOUT_MS);
    ws.addEventListener("open", () => this.#authenticate(ws));
    ws.addEventListener("message", (event) => this.#onMessage(ws, event));
    ws.addEventListener("close", (event) => this.#onClose(ws, event));
  }

  /** Throw the current socket away and connect again (it may be dead after sleep). */
  reconnect() {
    if (this.status === "unpaired") return;
    this.disconnect();
    this.attempt = 0;
    this.connect();
  }

  /** Pair with a one-time code from `phonepad pair`. The old token stays until it works. */
  pair(code) {
    this.pairCode = code.replace(/\D/g, "");
    this.disconnect();
    this.connect();
  }

  /** Forget the token and stop (the server keeps the device until `phonepad revoke`). */
  unpair() {
    this.tokens.clear();
    this.disconnect();
    this.#setStatus("unpaired");
  }

  disconnect() {
    this.#clear("retryTimer");
    this.#stopTimers();
    const ws = this.ws;
    this.ws = null;
    if (ws) ws.close(1000);
  }

  /** Send a protocol message; dropped (returns false) unless authenticated. */
  send(message) {
    if (!this.ready || this.ws?.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(message));
    return true;
  }

  #authenticate(ws) {
    this.#clear("connectTimer");
    const token = this.tokens.get();
    const hello = this.pairCode
      ? {
          type: "pair",
          v: PROTOCOL_VERSION,
          code: this.pairCode,
          name: this.deviceName,
          replaces: token ?? "",
        }
      : { type: "hello", v: PROTOCOL_VERSION, token };
    ws.send(JSON.stringify(hello));
  }

  #onMessage(ws, event) {
    if (ws !== this.ws) return;
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch {
      return;
    }
    switch (msg.type) {
      case "paired":
        this.tokens.set(msg.token);
        this.pairCode = null;
        break;
      case "welcome":
        this.attempt = 0;
        this.capabilities = msg.capabilities ?? [];
        this.serverVersion = msg.server_version ?? "";
        this.#setStatus("ready");
        this.#schedulePing(ws);
        break;
      case "pong":
        this.#clear("pongTimer");
        this.#schedulePing(ws);
        break;
      case "error":
        this.#onError(msg);
        break;
      default:
        break;
    }
  }

  #schedulePing(ws) {
    if (!this.capabilities.includes("ping")) return;
    this.#clear("pingTimer");
    this.pingTimer = this.timers.setTimeout(() => {
      if (ws !== this.ws || !this.send({ type: "ping" })) return;
      this.pongTimer = this.timers.setTimeout(() => this.#drop(ws), PONG_TIMEOUT_MS);
    }, PING_INTERVAL_MS);
  }

  /** Treat `ws` as dead: forget it and reconnect with backoff. */
  #drop(ws) {
    if (ws !== this.ws) return;
    ws.close(4000);
    this.#onClose(ws, { code: 1006 });
  }

  #onError(msg) {
    if (msg.code === "bad_code") {
      this.pairCode = null;
      this.#emit("pairerror", { message: msg.message });
      // Still paired from before? Then keep using that token.
      if (this.tokens.get()) this.#retrySoon();
      else this.#setStatus("unpaired");
    } else if (msg.code === "unauthorized" || msg.code === "revoked") {
      this.tokens.clear();
      this.#setStatus("unpaired");
    } else {
      this.#emit("error", { code: msg.code, message: msg.message });
    }
  }

  #retrySoon() {
    this.disconnect();
    this.retryTimer = this.timers.setTimeout(() => this.connect(), RETRY_MS[0]);
  }

  #onClose(ws, event) {
    if (ws !== this.ws) return;
    this.ws = null;
    this.#stopTimers();
    if (this.status === "unpaired" || this.retryTimer) return;
    if (event.code === 4401) {
      // Rejected credentials: do not hammer the server.
      this.#setStatus("offline");
      return;
    }
    this.#setStatus("offline");
    const delay = RETRY_MS[Math.min(this.attempt, RETRY_MS.length - 1)];
    this.attempt += 1;
    this.retryTimer = this.timers.setTimeout(() => {
      this.retryTimer = null;
      this.connect();
    }, delay);
  }

  #stopTimers() {
    this.#clear("connectTimer");
    this.#clear("pingTimer");
    this.#clear("pongTimer");
  }

  #clear(name) {
    if (this[name] !== null) this.timers.clearTimeout(this[name]);
    this[name] = null;
  }

  #setStatus(status) {
    this.status = status;
    this.#emit("status", { status, capabilities: this.capabilities });
  }

  #emit(type, detail) {
    this.dispatchEvent(new CustomEvent(type, { detail }));
  }
}
