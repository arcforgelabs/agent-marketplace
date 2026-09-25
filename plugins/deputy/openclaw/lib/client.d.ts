export declare class DeputyError extends Error {
    readonly httpStatus: number;
    readonly path: string;
    readonly body: unknown;
    readonly retryAfterSec?: number;
    constructor(httpStatus: number, path: string, body: unknown, retryAfterSec?: number);
}
export declare class DeputyRateLimitError extends DeputyError {
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
    unpublishedVendorLimit: true;
    localHardCapPerMinute: number;
};
export type RateGovernor = {
    setMaxRequestsPerMinute(value: number): void;
    snapshot(): GovernorSnapshot;
    acquire(signal: AbortSignal): Promise<void>;
    noteHeaders(headers: Headers, now?: number): void;
    note429(retryAfterSec: number, now?: number): void;
};
export type DeputyRequestOptions = {
    query?: Record<string, string | number | boolean | undefined | null>;
    body?: unknown;
    signal?: AbortSignal;
    redirect?: RequestRedirect;
};
export type DeputyClient = {
    request(method: string, path: string, options?: DeputyRequestOptions): Promise<unknown>;
    governor: RateGovernor;
    origin: string;
};
export type CreateDeputyClientOptions = {
    token: string;
    installHost: string;
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
export declare function createDeputyClient(options: CreateDeputyClientOptions): DeputyClient;
