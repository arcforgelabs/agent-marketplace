export type GhlPluginConfig = {
    locationId?: string;
    privateIntegrationToken?: string | {
        source: string;
        provider: string;
        id: string;
    };
    timezone?: string;
};
export type ResolvedGhlConfig = {
    locationId: string;
    token: string;
    timezone?: string;
};
export declare function resolveConfig(config: GhlPluginConfig): ResolvedGhlConfig;
export declare function capLimit(limit: number | undefined, fallback?: number, max?: number): number;
export declare function compact<T extends Record<string, unknown>>(input: T): Record<string, unknown>;
