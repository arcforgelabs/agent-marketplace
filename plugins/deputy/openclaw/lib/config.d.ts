export type SecretRef = {
    source: string;
    provider: string;
    id: string;
};
export type DeputyPluginConfig = {
    apiToken?: string | SecretRef;
    installHost?: string;
    maxRequestsPerMinute?: number;
    timezone?: string;
};
export type ResolvedDeputyConfig = {
    token: string;
    installHost: string;
    maxRequestsPerMinute: number;
    timezone?: string;
};
export declare const LOCAL_HARD_CAP_PER_MINUTE = 120;
export declare const DEFAULT_LOCAL_LIMIT_PER_MINUTE = 60;
export declare const QUERY_MAX = 500;
export declare const QUERY_DEFAULT = 100;
export declare const INSTALL_HOST_RE: RegExp;
export declare function capRequestsPerMinute(value: unknown): number;
export declare function validateInstallHost(value: unknown): string;
export declare function resolveConfig(config: DeputyPluginConfig): ResolvedDeputyConfig;
export declare function capLimit(value: unknown, fallback?: number, max?: number): number;
export declare function compact(input: Record<string, unknown>): Record<string, unknown>;
