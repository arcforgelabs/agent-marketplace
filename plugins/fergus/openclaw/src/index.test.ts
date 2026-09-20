import {describe, expect, it} from "vitest";
import {readFileSync} from "node:fs";
import {resolve} from "node:path";
import entry from "./index.js";
import {getToolPluginMetadata} from "openclaw/plugin-sdk/tool-plugin";

const expectedTools = [
  "fergus_status",
  "fergus_jobs",
  "fergus_quotes",
  "fergus_calendar",
  "fergus_customers",
  "fergus_sites",
  "fergus_contacts",
  "fergus_users",
  "fergus_notes",
  "fergus_tasks",
  "fergus_files",
  "fergus_enquiries",
  "fergus_invoices",
  "fergus_time",
  "fergus_stock",
  "fergus_pricebooks",
  "fergus_favourites",
];

describe("fergus plugin", () => {
  it("declares the full official-API tool surface", () => {
    expect(getToolPluginMetadata(entry)?.id).toBe("arcforgelabs-fergus");
    expect(getToolPluginMetadata(entry)?.tools.map((tool) => tool.name)).toEqual(expectedTools);
  });

  it("accepts protected store SecretRefs", () => {
    const manifest = readFileSync(resolve(import.meta.dirname, "../openclaw.plugin.json"), "utf8");
    expect(manifest).toContain('"const": "store"');
    expect(manifest).toContain('"path": "apiToken"');
    expect(manifest).not.toContain("privateIntegrationToken");
    expect(manifest).not.toContain("locationId");
  });

  it("exposes every tool through intended profiles with explicit safety metadata", () => {
    const manifest = JSON.parse(
      readFileSync(resolve(import.meta.dirname, "../openclaw.plugin.json"), "utf8"),
    );
    expect(Object.keys(manifest.toolMetadata)).toEqual(expectedTools);
    for (const name of expectedTools) {
      expect(manifest.toolMetadata[name].profiles).toEqual(["coding", "full"]);
      expect(manifest.toolMetadata[name].replaySafe).toBe(name === "fergus_status");
      expect(manifest.toolMetadata[name].sideEffecting).toBe(name !== "fergus_status");
    }
  });

  it("declares an OpenClaw floor without an upper bound", () => {
    const pkg = JSON.parse(readFileSync(resolve(import.meta.dirname, "../package.json"), "utf8"));
    expect(pkg.peerDependencies.openclaw).toBe(">=2026.9.3");
    expect(pkg.openclaw.compat.pluginApi).toBe(">=2026.9.3");
    expect(pkg.openclaw.compat.minGatewayVersion).toBe("2026.9.3");
    expect(pkg.peerDependencies.openclaw).not.toMatch("<=");
    expect(pkg.openclaw.compat.pluginApi).not.toMatch("<=");
  });
});
