import {describe, expect, it, vi} from "vitest";
import {createFergusClient, createRateGovernor, FergusError, FergusRateLimitError} from "./client.js";

function jsonResponse(status: number, body: unknown, headers?: Record<string, string>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {"content-type": "application/json", ...headers},
  });
}

function fakeClock() {
  let nowMs = 1_000_000;
  return {
    now: () => nowMs,
    async sleep(ms: number, signal?: AbortSignal) {
      signal?.throwIfAborted();
      nowMs += ms;
    },
  };
}

describe("fergus client", () => {
  it("sends bearer auth, identifying UA, and refuses redirects", async () => {
    const fetchImpl = vi.fn(async (input: URL | RequestInfo, init?: RequestInit) => {
      expect(String(input)).toBe("https://api.fergus.com/version");
      expect(init?.redirect).toBe("error");
      return jsonResponse(200, {version: "v1"});
    });
    const client = createFergusClient({
      token: "pat_test",
      fetchImpl: fetchImpl as unknown as typeof fetch,
      governor: createRateGovernor({maxRequestsPerMinute: 80}),
    });
    await expect(client.request("GET", "/version")).resolves.toEqual({version: "v1"});
    const headers = (fetchImpl.mock.calls[0]?.[1] as RequestInit).headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer pat_test");
    expect(headers["User-Agent"]).toBe("OpenClaw-Fergus/0.1.0");
  });

  it("retries GET 429 once using retry-after, then succeeds", async () => {
    const clock = fakeClock();
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(429, {error: "slow"}, {"retry-after": "0"}))
      .mockResolvedValueOnce(jsonResponse(200, {ok: true}));
    const client = createFergusClient({
      token: "pat_test",
      fetchImpl: fetchImpl as unknown as typeof fetch,
      governor: createRateGovernor({maxRequestsPerMinute: 80, now: clock.now, sleep: clock.sleep}),
      now: clock.now,
      sleep: clock.sleep,
    });
    await expect(client.request("GET", "/jobs")).resolves.toEqual({ok: true});
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("does not retry writes after 429", async () => {
    const clock = fakeClock();
    const fetchImpl = vi.fn(async () => jsonResponse(429, {error: "slow"}, {"retry-after": "1"}));
    const client = createFergusClient({
      token: "pat_test",
      fetchImpl: fetchImpl as unknown as typeof fetch,
      governor: createRateGovernor({maxRequestsPerMinute: 80, now: clock.now, sleep: clock.sleep}),
      now: clock.now,
      sleep: clock.sleep,
    });
    await expect(client.request("POST", "/jobs", {body: {jobType: "Quote"}})).rejects.toBeInstanceOf(
      FergusRateLimitError,
    );
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("does not retry writes after network failure and redacts the token", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error("pat_secret_value");
    });
    const client = createFergusClient({
      token: "pat_secret_value",
      fetchImpl: fetchImpl as unknown as typeof fetch,
      governor: createRateGovernor({maxRequestsPerMinute: 80}),
    });
    await expect(client.request("POST", "/jobs", {body: {}})).rejects.toSatisfy((error: unknown) => {
      expect(String(error)).toContain("verify the outcome");
      expect(String(error)).not.toContain("pat_secret_value");
      return true;
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("does not retry 401 and redacts bearer tokens in parsed bodies", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(401, {message: "Bearer pat_secret_value is invalid"}));
    const client = createFergusClient({
      token: "pat_secret_value",
      fetchImpl: fetchImpl as unknown as typeof fetch,
      governor: createRateGovernor({maxRequestsPerMinute: 80}),
    });
    await expect(client.request("GET", "/users/me")).rejects.toSatisfy((error: unknown) => {
      expect(error).toBeInstanceOf(FergusError);
      expect(String(error)).not.toContain("pat_secret_value");
      expect((error as FergusError).body).toEqual({message: "Bearer [redacted] is invalid"});
      return true;
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("rejects path traversal, query-in-path, and origin escape", async () => {
    const client = createFergusClient({
      token: "pat_test",
      fetchImpl: vi.fn() as unknown as typeof fetch,
      governor: createRateGovernor({maxRequestsPerMinute: 80}),
    });
    await expect(client.request("GET", "https://evil.example/steal")).rejects.toThrow("must start with '/'");
    await expect(client.request("GET", "//evil.example/steal")).rejects.toThrow("must start with '/'");
    await expect(client.request("GET", "/jobs/../company")).rejects.toThrow("must start with '/'");
    await expect(client.request("GET", "/jobs?pageSize=1")).rejects.toThrow("must start with '/'");
  });

  it("waits before the 81st request under the default 80/min local budget", async () => {
    const clock = fakeClock();
    const sleeps: number[] = [];
    const sleep = async (ms: number, signal?: AbortSignal) => {
      signal?.throwIfAborted();
      sleeps.push(ms);
      await clock.sleep(ms, signal);
    };
    const fetchImpl = vi.fn(async () => jsonResponse(200, {ok: true}));
    const client = createFergusClient({
      token: "pat_test",
      fetchImpl: fetchImpl as unknown as typeof fetch,
      governor: createRateGovernor({maxRequestsPerMinute: 80, now: clock.now, sleep}),
      now: clock.now,
      sleep,
    });
    for (let i = 0; i < 80; i += 1) {
      await client.request("GET", "/version");
    }
    expect(sleeps).toEqual([]);
    await client.request("GET", "/version");
    expect(sleeps.some((ms) => ms >= 1)).toBe(true);
    expect(fetchImpl).toHaveBeenCalledTimes(81);
  });
});
