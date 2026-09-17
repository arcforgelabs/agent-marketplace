export const FIELD_SCOPES = "catalog.read catalog.write quote.read quote.draft";
export class FieldPluginError extends Error {
    code;
    constructor(message, code = "config_error") {
        super(message);
        this.name = "FieldPluginError";
        this.code = code;
    }
}
export function normalizeOrigin(value) {
    let url;
    try {
        url = new URL(String(value ?? ""));
    }
    catch {
        throw new FieldPluginError("origin must be a valid URL");
    }
    if (!["http:", "https:"].includes(url.protocol)) {
        throw new FieldPluginError("origin must use http or https");
    }
    if (url.username || url.password || url.search || url.hash) {
        throw new FieldPluginError("origin must not contain credentials, query parameters, or fragments");
    }
    if (url.pathname !== "/" && url.pathname !== "") {
        throw new FieldPluginError("origin must not contain a path");
    }
    return url.origin;
}
export function resolveOrigin(config = {}) {
    const origin = normalizeOrigin(config.origin);
    return {
        origin,
        mcpUrl: `${origin}/mcp`,
        auth: "oauth",
        scopes: FIELD_SCOPES,
    };
}
export function mcpServerConfig(origin) {
    const resolved = resolveOrigin({ origin });
    return {
        url: resolved.mcpUrl,
        transport: "streamable-http",
        auth: "oauth",
        oauth: { scope: resolved.scopes },
        toolFilter: { include: ["field_*"] },
    };
}
