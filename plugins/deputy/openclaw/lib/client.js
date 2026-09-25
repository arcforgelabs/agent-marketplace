import { DEFAULT_LOCAL_LIMIT_PER_MINUTE, LOCAL_HARD_CAP_PER_MINUTE, capRequestsPerMinute, validateInstallHost, } from "./config.js";
const UA = "OpenClaw-Deputy/0.1.0";
const WINDOW_MS = 60_000;
const REQUEST_TIMEOUT_MS = 30_000;
export class DeputyError extends Error {
    httpStatus;
    path;
    body;
    retryAfterSec;
    constructor(httpStatus, path, body, retryAfterSec) {
        super(retryAfterSec !== undefined
            ? `Deputy request failed (${httpStatus}); retry after ${retryAfterSec}s; upstream body [redacted].`
            : `Deputy request failed (${httpStatus}); upstream body [redacted].`);
        this.name = "DeputyError";
        this.httpStatus = httpStatus;
        this.path = path;
        this.body = body;
        this.retryAfterSec = retryAfterSec;
    }
}
export class DeputyRateLimitError extends DeputyError {
    constructor(path, body, retryAfterSec) {
        super(429, path, body, retryAfterSec);
        this.name = "DeputyRateLimitError";
    }
}
function defaultNow() {
    return Date.now();
}
function defaultSleep(ms, signal) {
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
        signal.addEventListener("abort", onAbort, { once: true });
    });
}
export function createRateGovernor(options = {}) {
    let maxRequestsPerMinute = capRequestsPerMinute(options.maxRequestsPerMinute);
    const now = options.now ?? defaultNow;
    const sleep = options.sleep ?? defaultSleep;
    const sentAt = [];
    let headerRemaining = null;
    let headerResetAt = null;
    let last429 = null;
    let queued = 0;
    let chain = Promise.resolve();
    function prune(at) {
        while (sentAt.length && at - sentAt[0] >= WINDOW_MS)
            sentAt.shift();
    }
    function snapshot() {
        const at = now();
        prune(at);
        const localRemaining = Math.max(maxRequestsPerMinute - sentAt.length, 0);
        const remaining = headerRemaining === null ? localRemaining : Math.min(localRemaining, headerRemaining);
        const resetMs = headerResetAt !== null
            ? Math.max(headerResetAt - at, 0)
            : sentAt.length
                ? Math.max(WINDOW_MS - (at - sentAt[0]), 0)
                : 0;
        return {
            remaining,
            reset: Math.ceil(resetMs / 1000),
            queued,
            last429: last429 ? { at: new Date(last429.at).toISOString(), retryAfterSec: last429.retryAfterSec } : null,
            maxRequestsPerMinute,
            unpublishedVendorLimit: true,
            localHardCapPerMinute: LOCAL_HARD_CAP_PER_MINUTE,
        };
    }
    async function waitForSlot(signal) {
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
                await sleep(Math.max(WINDOW_MS - (at - sentAt[0]) + 1, 1), signal);
                continue;
            }
            sentAt.push(now());
            if (headerRemaining !== null && headerRemaining > 0)
                headerRemaining -= 1;
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
                release = () => { };
            };
            const run = chain.then(async () => {
                try {
                    await waitForSlot(signal);
                }
                finally {
                    release();
                }
            });
            chain = run.then(() => undefined, () => undefined);
            return run;
        },
        noteHeaders(headers, at = now()) {
            const remaining = headers.get("x-ratelimit-remaining");
            const reset = headers.get("x-ratelimit-reset");
            if (remaining !== null && remaining !== "") {
                const parsed = Number(remaining);
                if (Number.isFinite(parsed) && parsed >= 0)
                    headerRemaining = parsed;
            }
            if (reset !== null && reset !== "") {
                const seconds = Number(reset);
                if (Number.isFinite(seconds) && seconds >= 0)
                    headerResetAt = at + seconds * 1000;
            }
        },
        note429(retryAfterSec, at = now()) {
            last429 = { at, retryAfterSec };
            headerRemaining = 0;
            headerResetAt = at + Math.max(retryAfterSec, 0) * 1000;
        },
    };
}
const sharedGovernor = createRateGovernor({ maxRequestsPerMinute: DEFAULT_LOCAL_LIMIT_PER_MINUTE });
export function getSharedGovernor() {
    return sharedGovernor;
}
export function assertRelativeApiPath(path) {
    if (!path.startsWith("/v1/") ||
        path.startsWith("//") ||
        path.includes("\\") ||
        path.includes("://") ||
        path.includes("?") ||
        path.includes("#") ||
        /(^|\/)\.\.($|\/)/.test(path) ||
        /%2e%2e/i.test(path)) {
        throw new Error("Deputy path must start with '/v1/' and contain no traversal, query, or origin escape.");
    }
}
function parseBody(text) {
    if (!text)
        return {};
    try {
        return JSON.parse(text);
    }
    catch {
        return text.slice(0, 300);
    }
}
function redact(text, token) {
    return token ? text.split(token).join("[redacted]") : text;
}
function retryAfterSeconds(response) {
    const retryAfter = Number(response.headers.get("retry-after"));
    if (Number.isFinite(retryAfter) && retryAfter >= 0)
        return retryAfter;
    const reset = Number(response.headers.get("x-ratelimit-reset"));
    if (Number.isFinite(reset) && reset >= 0)
        return reset;
    return 1;
}
function isRetryableMethod(method) {
    return method === "GET" || method === "HEAD";
}
export function createDeputyClient(options) {
    const token = options.token;
    const installHost = validateInstallHost(options.installHost);
    const origin = `https://${installHost}`;
    const baseUrl = `${origin}/api`;
    const fetchImpl = options.fetchImpl ?? fetch;
    const governor = options.governor ?? sharedGovernor;
    if (options.maxRequestsPerMinute !== undefined) {
        governor.setMaxRequestsPerMinute(options.maxRequestsPerMinute);
    }
    const now = options.now ?? defaultNow;
    const sleep = options.sleep ?? defaultSleep;
    async function send(method, path, requestOptions, redirect) {
        assertRelativeApiPath(path);
        const url = new URL(baseUrl + path);
        if (url.origin !== origin)
            throw new Error("Invalid request origin.");
        for (const [key, value] of Object.entries(requestOptions.query ?? {})) {
            if (value === undefined || value === null || value === "")
                continue;
            url.searchParams.set(key, String(value));
        }
        const signal = AbortSignal.any([
            AbortSignal.timeout(REQUEST_TIMEOUT_MS),
            ...[options.signal, requestOptions.signal].filter((item) => Boolean(item)),
        ]);
        const retryable = isRetryableMethod(method);
        let retried429 = false;
        for (;;) {
            await governor.acquire(signal);
            signal.throwIfAborted();
            const headers = {
                Authorization: `Bearer ${token}`,
                Accept: "application/json",
                "User-Agent": UA,
            };
            let body;
            if (requestOptions.body !== undefined) {
                headers["Content-Type"] = "application/json";
                body = JSON.stringify(requestOptions.body);
            }
            let response;
            try {
                response = await fetchImpl(url, { method, headers, body, signal, redirect });
            }
            catch (error) {
                signal.throwIfAborted();
                const message = retryable
                    ? "Deputy network request failed."
                    : "Deputy network request failed; verify the outcome before retrying writes.";
                throw new Error(redact(message, token));
            }
            governor.noteHeaders(response.headers, now());
            if (response.status !== 429)
                return response;
            const waitSec = retryAfterSeconds(response);
            governor.note429(waitSec, now());
            const text = redact(await response.text(), token);
            const data = parseBody(text);
            if (retryable && !retried429) {
                retried429 = true;
                await sleep(Math.max(waitSec, 0) * 1000, signal);
                continue;
            }
            throw new DeputyRateLimitError(path, data, waitSec);
        }
    }
    return {
        governor,
        origin,
        async request(method, path, requestOptions = {}) {
            const response = await send(method, path, requestOptions, requestOptions.redirect ?? "error");
            const text = redact(await response.text(), token);
            const data = parseBody(text);
            if (response.ok)
                return data;
            if (response.status === 429) {
                throw new DeputyRateLimitError(path, data, retryAfterSeconds(response));
            }
            throw new DeputyError(response.status, path, data);
        },
    };
}
