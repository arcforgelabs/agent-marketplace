export type SecretRef = {
    source: string;
    provider: string;
    id: string;
};
export type HubSpotPluginConfig = {
    accessToken?: string | SecretRef;
    portalId?: string;
    timezone?: string;
};
export type ResolvedHubSpotConfig = {
    token: string;
    portalId?: string;
    timezone?: string;
};
export declare function resolveConfig(config: HubSpotPluginConfig): ResolvedHubSpotConfig;
export declare function capLimit(value: unknown, fallback?: number, max?: number): number;
export declare function compact(input: Record<string, unknown>): Record<string, unknown>;
