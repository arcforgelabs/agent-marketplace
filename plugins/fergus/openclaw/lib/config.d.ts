export type SecretRef = {
    source: string;
    provider: string;
    id: string;
};
export type FergusPluginConfig = {
    apiToken?: string | SecretRef;
    companyId?: string;
    maxRequestsPerMinute?: number;
    timezone?: string;
};
export type ResolvedFergusConfig = {
    token: string;
    companyId?: string;
    maxRequestsPerMinute: number;
    timezone?: string;
};
export declare const VENDOR_LIMIT_PER_MINUTE = 100;
export declare const DEFAULT_LOCAL_LIMIT_PER_MINUTE = 80;
export declare function capRequestsPerMinute(value: unknown): number;
export declare function resolveConfig(config: FergusPluginConfig): ResolvedFergusConfig;
export declare function capLimit(value: unknown, fallback?: number, max?: number): number;
export declare function compact(input: Record<string, unknown>): Record<string, unknown>;
