export declare class FergusError extends Error {
    readonly httpStatus: number;
    readonly path: string;
    readonly body: unknown;
    readonly retryAfterSec?: number;
    constructor(httpStatus: number, path: string, body: unknown, retryAfterSec?: number);
}
export declare class FergusRateLimitError extends FergusError {
    constructor(path: string, body: unknown, retryAfterSec: number);
}
export type GovernorSnapshot = {
    remaining: number | null;
    reset: number | null;
    queued: number;
    last429: {
        at: string;
        retryAfterSec: number;
    } | null;
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
export declare function createRateGovernor(options?: {
    maxRequestsPerMinute?: number;
    now?: () => number;
    sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
}): RateGovernor;
export declare function getSharedGovernor(): RateGovernor;
export declare function assertRelativeApiPath(path: string): void;
export declare function createFergusClient(options: CreateFergusClientOptions): FergusClient;
