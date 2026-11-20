// WebSocket connection to the laptop: authentication, pairing and automatic reconnects.
//
// Events (CustomEvent, details in `event.detail`):
//   "status"  { status: "connecting" | "ready" | "offline" | "unpaired", capabilities }
//   "error"   { code, message }          server-reported problem (not fatal)
//   "pairerror" { message }              the pairing code was rejected

export const PROTOCOL_VERSION = 1;
const RETRY_MS = [500, 1000, 2000, 4000, 5000];

export class Connection extends EventTarget {
  /**
   * @param {string} url  WebSocket URL
   * @param {{ get(): string|null, set(t: string): void, clear(): void }} tokens
   * @param {string} deviceName  name sent when pairing
   */
  constructor(url, tokens, deviceName) {
    super();
    this.url = url;
    this.tokens = tokens;
    this.deviceName = deviceName;
    this.ws = null;
    this.status = "offline";
    this.capabilities = [];
    this.serverVersion = "";
    this.pairCode = null;
    this.attempt = 0;
    this.retryTimer = null;
  }

  get ready() {
    return this.status === "ready";
  }

  /** Connect if paired (or a pairing code is pending) and not already connected. */
  connect() {
    clearTimeout(this.retryTimer);
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) return;
    if (!this.tokens.get() && !this.pairCode) {
      this.#setStatus("unpaired");
      return;
    }
    this.#setStatus("connecting");
    const ws = new WebSocket(this.url);
    this.ws = ws;
    ws.addEventListener("open", () => this.#authenticate(ws));
    ws.addEventListener("message", (event) => this.#onMessage(ws, event));
    ws.addEventListener("close", (event) => this.#onClose(ws, event));
  }

  /** Pair with a one-time code from `phonepad pair`. */
  pair(code) {
    this.pairCode = code.replace(/\D/g, "");
    this.tokens.clear();
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
    clearTimeout(this.retryTimer);
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
    const token = this.tokens.get();
    const hello = token
      ? { type: "hello", v: PROTOCOL_VERSION, token }
      : { type: "pair", v: PROTOCOL_VERSION, code: this.pairCode ?? "", name: this.deviceName };
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
        break;
      case "error":
        this.#onError(msg);
        break;
      default:
        break;
    }
  }

  #onError(msg) {
    if (msg.code === "bad_code") {
      this.pairCode = null;
      this.#emit("pairerror", { message: msg.message });
      this.#setStatus("unpaired");
    } else if (msg.code === "unauthorized" || msg.code === "revoked") {
      this.tokens.clear();
      this.#setStatus("unpaired");
    } else {
      this.#emit("error", { code: msg.code, message: msg.message });
    }
  }

  #onClose(ws, event) {
    if (ws !== this.ws) return;
    this.ws = null;
    if (this.status === "unpaired" || event.code === 4401 || event.code === 4400) {
      // Do not hammer the server with a rejected token or a broken client.
      if (this.status !== "unpaired") this.#setStatus("offline");
      return;
    }
    this.#setStatus("offline");
    const delay = RETRY_MS[Math.min(this.attempt, RETRY_MS.length - 1)];
    this.attempt += 1;
    this.retryTimer = setTimeout(() => this.connect(), delay);
  }

  #setStatus(status) {
    this.status = status;
    this.#emit("status", { status, capabilities: this.capabilities });
  }

  #emit(type, detail) {
    this.dispatchEvent(new CustomEvent(type, { detail }));
  }
}
