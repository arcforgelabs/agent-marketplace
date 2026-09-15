export declare const FIELD_SCOPES = "catalog.read catalog.write quote.read quote.draft";
export declare class FieldPluginError extends Error {
    code: string;
    constructor(message: string, code?: string);
}
export type FieldPluginConfig = {
    origin?: string;
};
export declare function normalizeOrigin(value: unknown): string;
export declare function resolveOrigin(config?: FieldPluginConfig): {
    origin: string;
    mcpUrl: string;
    auth: "oauth";
    scopes: string;
};
export declare function mcpServerConfig(origin: string): {
    url: string;
    transport: string;
    auth: string;
    oauth: {
        scope: string;
    };
    toolFilter: {
        include: string[];
    };
};
