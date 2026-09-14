import { describe, expect, it, vi } from "vitest";
import { createGhlClient, GhlError } from "./client.js";
import { contacts } from "./operations.js";
import { resolveConfig } from "./config.js";

function jsonResponse(status: number, body: unknown, headers?: Record<string, string>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

describe("ghl client", () => {
  it("sends version, browser UA, and bearer auth", async () => {
    const fetchImpl = vi.fn(async (input: URL | RequestInfo) => {
      expect(String(input)).toBe("https://services.leadconnectorhq.com/locations/loc_123");
      return jsonResponse(200, { location: { id: "loc_123", name: "Acme Landscaping" } });
    });
    const client = createGhlClient({ token: "pit_test", fetchImpl: fetchImpl as unknown as typeof fetch });
    await client.request("GET", "/locations/loc_123");
    const init = fetchImpl.mock.calls[0]?.[1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer pit_test");
    expect(headers.Version).toBe("2021-07-28");
    expect(headers["User-Agent"]).toContain("Mozilla/5.0");
  });

  it("retries 429 then succeeds", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(429, { message: "slow down" }, { "retry-after": "0" }))
      .mockResolvedValueOnce(jsonResponse(200, { ok: true }));
    const client = createGhlClient({ token: "pit_test", fetchImpl: fetchImpl as unknown as typeof fetch });
    await expect(client.request("GET", "/contacts/abc")).resolves.toEqual({ ok: true });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("does not retry 401 and redacts bearer tokens in errors", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(401, { message: "Bearer pit_secret_value is invalid" }));
    const client = createGhlClient({ token: "pit_secret_value", fetchImpl: fetchImpl as unknown as typeof fetch });
    await expect(client.request("GET", "/contacts/abc")).rejects.toSatisfy((error: unknown) => {
      expect(error).toBeInstanceOf(GhlError);
      expect(String(error)).not.toContain("pit_secret_value");
      expect(String(error)).toContain("[redacted]");
      return true;
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("rejects non-path URLs", async () => {
    const client = createGhlClient({ token: "pit_test", fetchImpl: vi.fn() as unknown as typeof fetch });
    await expect(client.request("GET", "https://evil.example/steal")).rejects.toThrow("must start with '/'" );
  });
});

describe("ghl contacts operations", () => {
  it("pins search to the configured location", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(200, { contacts: [] }));
    const client = createGhlClient({ token: "pit_test", fetchImpl: fetchImpl as unknown as typeof fetch });
    const config = resolveConfig({
      locationId: "loc_configured",
      privateIntegrationToken: "pit_test",
    });
    await contacts(client, config, { action: "search", query: "Alex Citizen" });
    expect(String(fetchImpl.mock.calls[0]?.[0])).toContain("locationId=loc_configured");
    expect(String(fetchImpl.mock.calls[0]?.[0])).toContain("query=Alex+Citizen");
  });
});
