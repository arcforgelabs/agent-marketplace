const DEFAULT_BASE = "https://services.leadconnectorhq.com";
const VERSION = "2021-07-28";
const UA = "Mozilla/5.0 (OpenClaw-GHL)";
const MAX_ATTEMPTS = 3;

export class GhlError extends Error {
  readonly httpStatus: number;
  readonly path: string;
  readonly body: unknown;

  constructor(httpStatus: number, path: string, body: unknown) {
    super(`HighLevel request failed (${httpStatus}); upstream body [redacted].`);
    this.name = "GhlError";
    this.httpStatus = httpStatus;
    this.path = path;
    this.body = undefined;
  }
}

export type GhlRequestOptions = {
  query?: Record<string, string | number | boolean | undefined | null>;
  body?: unknown;
  signal?: AbortSignal;
};

export type GhlClient = {
  request(method: string, path: string, options?: GhlRequestOptions): Promise<unknown>;
};

export function createGhlClient(options: {
  token: string;
  baseUrl?: string;
  fetchImpl?: typeof fetch;
  signal?: AbortSignal;
}): GhlClient {
  const token = options.token;
  const baseUrl = (options.baseUrl ?? DEFAULT_BASE).replace(/\/$/, "");
  const fetchImpl = options.fetchImpl ?? fetch;

  return {
    async request(method, path, requestOptions = {}) {
      if (!path.startsWith("/") || path.startsWith("//") || path.includes("\\") || /(^|\/)\.\.?($|\/)/.test(path)) {
        throw new Error("HighLevel path must start with '/'.");
      }
      const url = new URL(`${baseUrl}${path}`);
      if (url.origin !== new URL(baseUrl).origin) throw new Error("Invalid request origin.");
      const signal = AbortSignal.any([AbortSignal.timeout(30000), ...[options.signal, requestOptions.signal].filter((s): s is AbortSignal => !!s)]);
      const retryable = method === "GET" || method === "HEAD";
      for (const [key, value] of Object.entries(requestOptions.query ?? {})) {
        if (value === undefined || value === null || value === "") continue;
        url.searchParams.set(key, String(value));
      }

      let lastError: unknown;
      for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
        signal.throwIfAborted();
        const headers: Record<string, string> = {
          Authorization: `Bearer ${token}`,
          Version: VERSION,
          Accept: "application/json",
          "User-Agent": UA,
        };
        if (requestOptions.body !== undefined) {
          headers["Content-Type"] = "application/json";
        }

        let response: Response;
        try {
          response = await fetchImpl(url, {
            method,
            headers,
            body: requestOptions.body === undefined ? undefined : JSON.stringify(requestOptions.body),
            signal,
            redirect: "error",
          });
        } catch (error) {
          lastError = new Error("HighLevel network request failed; verify the outcome before retrying writes.");
          signal.throwIfAborted();
          if (!retryable || attempt >= MAX_ATTEMPTS - 1) throw lastError;
          await sleep(400 * (attempt + 1), signal);
          continue;
        }

        const text = (await response.text()).split(token).join("[redacted]");
        const data = parseBody(text);
        if (response.ok) return data;

        if (retryable && shouldRetry(response.status) && attempt < MAX_ATTEMPTS - 1) {
          await sleep(retryDelayMs(response, attempt), signal);
          continue;
        }
        throw new GhlError(response.status, path, data);
      }
      throw lastError;
    },
  };
}

function parseBody(text: string): unknown {
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return text.slice(0, 300);
  }
}

function shouldRetry(httpStatus: number): boolean {
  return httpStatus === 429 || httpStatus >= 500;
}

function retryDelayMs(response: Response, attempt: number): number {
  const retryAfter = response.headers.get("retry-after");
  if (retryAfter) {
    const seconds = Number(retryAfter);
    if (Number.isFinite(seconds) && seconds >= 0) return Math.min(seconds * 1000, 10_000);
  }
  return 500 * (attempt + 1);
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const onAbort = () => { clearTimeout(timer); reject(signal.reason); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", onAbort); resolve(); }, ms);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}
