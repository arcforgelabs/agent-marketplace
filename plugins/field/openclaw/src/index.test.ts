import { readFileSync, existsSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { getToolPluginMetadata } from "openclaw/plugin-sdk/tool-plugin";
import entry from "./index.js";

describe("field plugin", () => {
  it("is an OAuth MCP connector, not a bearer CLI", () => {
    const metadata = getToolPluginMetadata(entry);
    expect(metadata?.id).toBe("arcforgelabs-field");
    expect(metadata?.tools.map((tool) => tool.name)).toEqual(["field_connection_status"]);
    expect(existsSync(new URL("./cli.ts", import.meta.url))).toBe(false);
    expect(existsSync(new URL("./client.ts", import.meta.url))).toBe(false);
  });

  it("packaged manifest has origin only and no token SecretRef", () => {
    const manifest = JSON.parse(readFileSync(new URL("../openclaw.plugin.json", import.meta.url), "utf8"));
    expect(manifest.id).toBe("arcforgelabs-field");
    expect(manifest.contracts.tools).toEqual(["field_connection_status"]);
    expect(manifest.configSchema.properties.origin).toBeTruthy();
    expect(manifest.configSchema.properties.tokenEnv).toBeUndefined();
    expect(manifest.configSchema.properties.token).toBeUndefined();
    expect(manifest.configContracts?.secretInputs).toBeUndefined();
    expect(manifest.mcpServers.field.auth).toBe("oauth");
    expect(manifest.mcpServers.field.transport).toBe("streamable-http");
    expect(manifest.mcpServers.field.toolFilter.include).toEqual(["field_*"]);
  });

  it("declares an OpenClaw floor without an upper bound", () => {
    const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
    expect(pkg.peerDependencies.openclaw).toBe(">=2026.9.3");
    expect(pkg.openclaw.compat.pluginApi).toBe(">=2026.9.3");
    expect(pkg.openclaw.compat.minGatewayVersion).toBe("2026.9.3");
    expect(pkg.peerDependencies.openclaw).not.toMatch("<=");
    expect(pkg.openclaw.compat.pluginApi).not.toMatch("<=");
  });
});
