import {DEFAULT_LOCAL_LIMIT_PER_MINUTE, VENDOR_LIMIT_PER_MINUTE, capRequestsPerMinute} from "./config.js";

const BASE = "https://api.fergus.com";
const UA = "OpenClaw-Fergus/0.1.0";
const WINDOW_MS = 60_000;
const REQUEST_TIMEOUT_MS = 30_000;

export class FergusError extends Error {
  readonly httpStatus: number;
  readonly path: string;
  readonly body: unknown;
  readonly retryAfterSec?: number;

  constructor(httpStatus: number, path: string, body: unknown, retryAfterSec?: number) {
    super(
      retryAfterSec !== undefined
        ? `Fergus request failed (${httpStatus}); retry after ${retryAfterSec}s; upstream body [redacted].`
        : `Fergus request failed (${httpStatus}); upstream body [redacted].`,
    );
    this.name = "FergusError";
    this.httpStatus = httpStatus;
    this.path = path;
    this.body = body;
    this.retryAfterSec = retryAfterSec;
  }
}

export class FergusRateLimitError extends FergusError {
  constructor(path: string, body: unknown, retryAfterSec: number) {
    super(429, path, body, retryAfterSec);
    this.name = "FergusRateLimitError";
  }
}

export type GovernorSnapshot = {
  remaining: number | null;
  reset: number | null;
  queued: number;
  last429: {at: string; retryAfterSec: number} | null;
  maxRequestsPerMinute: number;
  vendorLimitPerMinute: number;
};

export type RateGovernor = {
  setMaxRequestsPerMinute(value: number): void;
  snapshot(): GovernorSnapshot;
  acquire(signal: AbortSignal): Promise<void>;
  noteHeaders(headers: Headers, now?: number): void;
  note429(retryAfterSec: number, now?: number): void;
};

export type FergusRequestOptions = {
  query?: Record<string, string | number | boolean | undefined | null>;
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
  redirect?: RequestRedirect;
};

export type FergusClient = {
  request(method: string, path: string, options?: FergusRequestOptions): Promise<unknown>;
  download(path: string, options?: Omit<FergusRequestOptions, "body" | "form" | "redirect">): Promise<{
    status: number;
    location: string | null;
    cache: false;
    body: unknown;
  }>;
  governor: RateGovernor;
};

export type CreateFergusClientOptions = {
  token: string;
  baseUrl?: string;
  fetchImpl?: typeof fetch;
  signal?: AbortSignal;
  governor?: RateGovernor;
  maxRequestsPerMinute?: number;
  now?: () => number;
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
};

function defaultNow(): number {
  return Date.now();
}

function defaultSleep(ms: number, signal: AbortSignal): Promise<void> {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    signal.addEventListener("abort", onAbort, {once: true});
  });
}

export function createRateGovernor(options: {
  maxRequestsPerMinute?: number;
  now?: () => number;
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
} = {}): RateGovernor {
  let maxRequestsPerMinute = capRequestsPerMinute(options.maxRequestsPerMinute);
  const now = options.now ?? defaultNow;
  const sleep = options.sleep ?? defaultSleep;
  const sentAt: number[] = [];
  let headerRemaining: number | null = null;
  let headerResetAt: number | null = null;
  let last429: {at: number; retryAfterSec: number} | null = null;
  let queued = 0;
  let chain = Promise.resolve();

  function prune(at: number): void {
    while (sentAt.length && at - sentAt[0]! >= WINDOW_MS) sentAt.shift();
  }

  function snapshot(): GovernorSnapshot {
    const at = now();
    prune(at);
    const localRemaining = Math.max(maxRequestsPerMinute - sentAt.length, 0);
    const remaining = headerRemaining === null ? localRemaining : Math.min(localRemaining, headerRemaining);
    const resetMs = headerResetAt !== null
      ? Math.max(headerResetAt - at, 0)
      : sentAt.length
        ? Math.max(WINDOW_MS - (at - sentAt[0]!), 0)
        : 0;
    return {
      remaining,
      reset: Math.ceil(resetMs / 1000),
      queued,
      last429: last429 ? {at: new Date(last429.at).toISOString(), retryAfterSec: last429.retryAfterSec} : null,
      maxRequestsPerMinute,
      vendorLimitPerMinute: VENDOR_LIMIT_PER_MINUTE,
    };
  }

  async function waitForSlot(signal: AbortSignal): Promise<void> {
    for (;;) {
      signal.throwIfAborted();
      const at = now();
      prune(at);
      if (headerRemaining === 0) {
        const wait = headerResetAt !== null ? Math.max(headerResetAt - at, 1) : 1000;
        await sleep(wait, signal);
        headerRemaining = null;
        continue;
      }
      if (sentAt.length >= maxRequestsPerMinute) {
        await sleep(Math.max(WINDOW_MS - (at - sentAt[0]!) + 1, 1), signal);
        continue;
      }
      sentAt.push(now());
      if (headerRemaining !== null && headerRemaining > 0) headerRemaining -= 1;
      return;
    }
  }

  return {
    setMaxRequestsPerMinute(value) {
      maxRequestsPerMinute = capRequestsPerMinute(value);
    },
    snapshot,
    acquire(signal) {
      queued += 1;
      let release = () => {
        queued -= 1;
        release = () => {};
      };
      const run = chain.then(async () => {
        try {
          await waitForSlot(signal);
        } finally {
          release();
        }
      });
      chain = run.then(
        () => undefined,
        () => undefined,
      );
      return run;
    },
    noteHeaders(headers, at = now()) {
      const remaining = headers.get("x-ratelimit-remaining");
      const reset = headers.get("x-ratelimit-reset");
      if (remaining !== null && remaining !== "") {
        const parsed = Number(remaining);
        if (Number.isFinite(parsed) && parsed >= 0) headerRemaining = parsed;
      }
      if (reset !== null && reset !== "") {
        const seconds = Number(reset);
        if (Number.isFinite(seconds) && seconds >= 0) headerResetAt = at + seconds * 1000;
      }
    },
    note429(retryAfterSec, at = now()) {
      last429 = {at, retryAfterSec};
      headerRemaining = 0;
      headerResetAt = at + Math.max(retryAfterSec, 0) * 1000;
    },
  };
}

const sharedGovernor = createRateGovernor({maxRequestsPerMinute: DEFAULT_LOCAL_LIMIT_PER_MINUTE});

export function getSharedGovernor(): RateGovernor {
  return sharedGovernor;
}

export function assertRelativeApiPath(path: string): void {
  if (
    !path.startsWith("/") ||
    path.startsWith("//") ||
    path.includes("\\") ||
    path.includes("://") ||
    path.includes("?") ||
    path.includes("#") ||
    /(^|\/)\.\.($|\/)/.test(path) ||
    /%2e%2e/i.test(path)
  ) {
    throw new Error("Fergus path must start with '/' and contain no traversal, query, or origin escape.");
  }
}

function parseBody(text: string): unknown {
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return text.slice(0, 300);
  }
}

function redact(text: string, token: string): string {
  return token ? text.split(token).join("[redacted]") : text;
}

function retryAfterSeconds(response: Response): number {
  const retryAfter = Number(response.headers.get("retry-after"));
  if (Number.isFinite(retryAfter) && retryAfter >= 0) return retryAfter;
  const reset = Number(response.headers.get("x-ratelimit-reset"));
  if (Number.isFinite(reset) && reset >= 0) return reset;
  return 1;
}

function isRetryableMethod(method: string): boolean {
  return method === "GET" || method === "HEAD";
}

export function createFergusClient(options: CreateFergusClientOptions): FergusClient {
  const token = options.token;
  const baseUrl = (options.baseUrl ?? BASE).replace(/\/$/, "");
  const origin = new URL(baseUrl).origin;
  if (origin !== "https://api.fergus.com" && options.baseUrl === undefined) {
    throw new Error("Fergus client is pinned to https://api.fergus.com.");
  }
  const fetchImpl = options.fetchImpl ?? fetch;
  const governor = options.governor ?? sharedGovernor;
  if (options.maxRequestsPerMinute !== undefined) {
    governor.setMaxRequestsPerMinute(options.maxRequestsPerMinute);
  }
  const now = options.now ?? defaultNow;
  const sleep = options.sleep ?? defaultSleep;

  async function send(
    method: string,
    path: string,
    requestOptions: FergusRequestOptions,
    redirect: RequestRedirect,
  ): Promise<Response> {
    assertRelativeApiPath(path);
    const url = new URL(baseUrl + path);
    if (url.origin !== origin) throw new Error("Invalid request origin.");
    for (const [key, value] of Object.entries(requestOptions.query ?? {})) {
      if (value === undefined || value === null || value === "") continue;
      url.searchParams.set(key, String(value));
    }
    const signal = AbortSignal.any([
      AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      ...[options.signal, requestOptions.signal].filter((item): item is AbortSignal => Boolean(item)),
    ]);
    const retryable = isRetryableMethod(method);
    let retried429 = false;

    for (;;) {
      await governor.acquire(signal);
      signal.throwIfAborted();
      const headers: Record<string, string> = {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
        "User-Agent": UA,
      };
      let body: BodyInit | undefined;
      if (requestOptions.form) {
        body = requestOptions.form;
      } else if (requestOptions.body !== undefined) {
        headers["Content-Type"] = "application/json";
        body = JSON.stringify(requestOptions.body);
      }
      let response: Response;
      try {
        response = await fetchImpl(url, {method, headers, body, signal, redirect});
      } catch (error) {
        signal.throwIfAborted();
        const message = retryable
          ? "Fergus network request failed."
          : "Fergus network request failed; verify the outcome before retrying writes.";
        throw new Error(redact(message, token));
      }
      governor.noteHeaders(response.headers, now());
      if (response.status !== 429) return response;

      const waitSec = retryAfterSeconds(response);
      governor.note429(waitSec, now());
      const text = redact(await response.text(), token);
      const data = parseBody(text);
      if (retryable && !retried429) {
        retried429 = true;
        await sleep(Math.max(waitSec, 0) * 1000, signal);
        continue;
      }
      throw new FergusRateLimitError(path, data, waitSec);
    }
  }

  return {
    governor,
    async request(method, path, requestOptions = {}) {
      const response = await send(method, path, requestOptions, requestOptions.redirect ?? "error");
      const text = redact(await response.text(), token);
      const data = parseBody(text);
      if (response.ok) return data;
      if (response.status === 429) {
        throw new FergusRateLimitError(path, data, retryAfterSeconds(response));
      }
      throw new FergusError(response.status, path, data);
    },
    async download(path, requestOptions = {}) {
      const response = await send("GET", path, requestOptions, "manual");
      const location = response.headers.get("location");
      const text = redact(await response.text(), token);
      const data = parseBody(text);
      if (response.status === 302 || response.status === 301 || response.status === 303 || response.status === 307 || response.status === 308) {
        const signed = location ?? (typeof data === "object" && data && "location" in data ? String((data as {location?: unknown}).location ?? "") : "");
        return {status: response.status, location: signed || location, cache: false, body: data};
      }
      if (response.ok) {
        const signed = location ?? (typeof data === "object" && data && "location" in data ? String((data as {location?: unknown}).location ?? "") : null);
        return {status: response.status, location: signed, cache: false, body: data};
      }
      throw new FergusError(response.status, path, data);
    },
  };
}
