import { Type } from "typebox";
import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";
import { FieldPluginError, mcpServerConfig, resolveOrigin } from "./origin.js";
const configSchema = Type.Object({
    origin: Type.String({
        format: "uri",
        pattern: "^https?://",
        description: "Customer's Field public origin, with no path, query, credentials, or fragment.",
    }),
}, { additionalProperties: false });
export default defineToolPlugin({
    id: "arcforgelabs-field",
    name: "Field by Arc Forge",
    description: "Connect OpenClaw to a customer's Field instance with OAuth. Quote and catalog tools come from Field MCP after login.",
    configSchema,
    tools: (tool) => [
        tool({
            name: "field_connection_status",
            label: "Field Connection",
            description: "Show the Field origin and the exact OAuth MCP login command. Does not call Field or reveal tokens.",
            parameters: Type.Object({}, { additionalProperties: false }),
            async execute(_params, config) {
                if (!config?.origin) {
                    throw new FieldPluginError("Set plugins.entries.arcforgelabs-field.config.origin to the customer's Field HTTPS origin");
                }
                const resolved = resolveOrigin(config);
                return {
                    origin: resolved.origin,
                    mcpUrl: resolved.mcpUrl,
                    auth: resolved.auth,
                    scopes: resolved.scopes,
                    set: `openclaw mcp set field '${JSON.stringify(mcpServerConfig(resolved.origin))}'`,
                    login: "openclaw mcp login field",
                };
            },
        }),
    ],
});
