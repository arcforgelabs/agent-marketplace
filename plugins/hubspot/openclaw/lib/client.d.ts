export declare class HubSpotError extends Error {
    readonly httpStatus: number;
    readonly path: string;
    readonly body: unknown;
    constructor(httpStatus: number, path: string, body: unknown);
}
export type RequestOptions = {
    query?: Record<string, string | number | boolean | undefined | null>;
    body?: unknown;
    signal?: AbortSignal;
};
export type HubSpotClient = {
    request(method: string, path: string, options?: RequestOptions): Promise<any>;
};
export declare function createHubSpotClient(options: {
    token: string;
    baseUrl?: string;
    fetchImpl?: typeof fetch;
    signal?: AbortSignal;
}): HubSpotClient;
