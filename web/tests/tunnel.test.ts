import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DEFAULT_API_URL, apiBase, proxiedHeaders } from "../src/lib/tunnel.ts";

describe("tunnel mode", () => {
  it("API base: /api in tunnel mode, the backend directly by default", () => {
    assert.equal(apiBase("/api"), "/api");
    assert.equal(apiBase("/api/"), "/api");
    assert.equal(apiBase(undefined), DEFAULT_API_URL);
    assert.equal(apiBase(""), "http://localhost:8000");
    assert.equal(apiBase("http://localhost:8000"), "http://localhost:8000");
  });

  it("the proxy replaces any browser-sent secret with the server's and marks the call as forwarded", () => {
    const h = proxiedHeaders(new Headers({ "x-agent-secret": "forged", accept: "text/event-stream" }), "server-secret", "abc.ngrok-free.app");
    assert.equal(h.get("x-agent-secret"), "server-secret");
    assert.equal(h.get("accept"), "text/event-stream");
    assert.equal(h.get("x-forwarded-host"), "abc.ngrok-free.app");
    const none = proxiedHeaders(new Headers({ "x-agent-secret": "forged" }), undefined, "localhost:3000");
    assert.equal(none.get("x-agent-secret"), null);
    const fwd = proxiedHeaders(new Headers({ "x-forwarded-for": "1.2.3.4" }), "s", "h");
    assert.equal(fwd.get("x-forwarded-host"), null);
    assert.equal(fwd.get("x-forwarded-for"), "1.2.3.4");
  });

  it("the secret is read only server side (proxy.ts), never through a NEXT_PUBLIC_ variable", () => {
    const proxy = readFileSync(new URL("../src/proxy.ts", import.meta.url), "utf8");
    assert.match(proxy, /process\.env\.AGENT_TOOL_SECRET/);
    assert.match(proxy, /matcher: "\/api\/:path\*"/);
    const cfg = readFileSync(new URL("../next.config.ts", import.meta.url), "utf8");
    assert.match(cfg, /source: "\/api\/:path\*"/);
    assert.doesNotMatch(cfg + proxy, /NEXT_PUBLIC_AGENT|NEXT_PUBLIC_.*SECRET/);
  });
});
