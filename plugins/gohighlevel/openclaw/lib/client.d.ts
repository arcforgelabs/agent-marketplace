export declare class GhlError extends Error {
    readonly httpStatus: number;
    readonly path: string;
    readonly body: unknown;
    constructor(httpStatus: number, path: string, body: unknown);
}
export type GhlRequestOptions = {
    query?: Record<string, string | number | boolean | undefined | null>;
    body?: unknown;
    signal?: AbortSignal;
};
export type GhlClient = {
    request(method: string, path: string, options?: GhlRequestOptions): Promise<unknown>;
};
export declare function createGhlClient(options: {
    token: string;
    baseUrl?: string;
    fetchImpl?: typeof fetch;
    signal?: AbortSignal;
}): GhlClient;
