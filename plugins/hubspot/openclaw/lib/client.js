const BASE = "https://api.hubapi.com";
const UA = "OpenClaw-HubSpot/0.1.0";
const MAX_ATTEMPTS = 3;
export class HubSpotError extends Error {
    httpStatus;
    path;
    body;
    constructor(httpStatus, path, body) {
        super(`HubSpot request failed (${httpStatus}); upstream body [redacted].`);
        this.httpStatus = httpStatus;
        this.path = path;
        this.body = body;
        this.name = "HubSpotError";
    }
}
export function createHubSpotClient(options) {
    const baseUrl = (options.baseUrl ?? BASE).replace(/\/$/, "");
    const origin = new URL(baseUrl).origin;
    const fetchImpl = options.fetchImpl ?? fetch;
    return { async request(method, path, requestOptions = {}) {
            if (!path.startsWith("/") || path.startsWith("//") || path.includes("\\") || /(^|\/)\.\.?($|\/)/.test(path))
                throw new Error("HubSpot path must start with '/' and contain no traversal segments.");
            const url = new URL(baseUrl + path);
            if (url.origin !== origin)
                throw new Error("Invalid request origin.");
            for (const [key, value] of Object.entries(requestOptions.query ?? {}))
                if (value !== undefined && value !== null && value !== "")
                    url.searchParams.set(key, String(value));
            const signal = AbortSignal.any([AbortSignal.timeout(30_000), ...[options.signal, requestOptions.signal].filter((s) => Boolean(s))]);
            const retryable = method === "GET" || method === "HEAD";
            let lastError;
            for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
                signal.throwIfAborted();
                let response;
                try {
                    response = await fetchImpl(url, { method, headers: { Authorization: `Bearer ${options.token}`, Accept: "application/json", "User-Agent": UA, ...(requestOptions.body === undefined ? {} : { "Content-Type": "application/json" }) }, body: requestOptions.body === undefined ? undefined : JSON.stringify(requestOptions.body), signal, redirect: "error" });
                }
                catch {
                    lastError = new Error(retryable ? "HubSpot network request failed." : "HubSpot network request failed; verify the outcome before retrying writes.");
                    signal.throwIfAborted();
                    if (!retryable || attempt === MAX_ATTEMPTS - 1)
                        throw lastError;
                    await delay(400 * (attempt + 1), signal);
                    continue;
                }
                const text = (await response.text()).split(options.token).join("[redacted]");
                const data = parse(text);
                if (response.ok)
                    return data;
                if (retryable && (response.status === 429 || response.status >= 500) && attempt < MAX_ATTEMPTS - 1) {
                    await delay(retryAfter(response, attempt), signal);
                    continue;
                }
                throw new HubSpotError(response.status, path, data);
            }
            throw lastError ?? new Error("HubSpot request failed.");
        } };
}
function parse(text) { if (!text)
    return {}; try {
    return JSON.parse(text);
}
catch {
    return text.slice(0, 300);
} }
function retryAfter(response, attempt) { const value = Number(response.headers.get("retry-after")); return Number.isFinite(value) && value >= 0 ? Math.min(value * 1000, 10_000) : 500 * (attempt + 1); }
function delay(ms, signal) { signal.throwIfAborted(); return new Promise((resolve, reject) => { const timer = setTimeout(resolve, ms); signal.addEventListener("abort", () => { clearTimeout(timer); reject(signal.reason); }, { once: true }); }); }
