import { describe, expect, it } from "vitest";
import entry from "./index.js";
import { getToolPluginMetadata } from "openclaw/plugin-sdk/tool-plugin";

const expectedTools = [
  "ghl_status",
  "ghl_contacts",
  "ghl_notes",
  "ghl_tasks",
  "ghl_conversations",
  "ghl_messages",
  "ghl_opportunities",
  "ghl_pipelines",
  "ghl_custom_fields",
  "ghl_calendars",
  "ghl_workflows",
  "ghl_users",
  "ghl_tags",
];

describe("gohighlevel plugin", () => {
  it("declares the full CRM tool surface", () => {
    expect(getToolPluginMetadata(entry)?.id).toBe("arcforgelabs-gohighlevel");
    expect(getToolPluginMetadata(entry)?.tools.map((tool) => tool.name)).toEqual(expectedTools);
  });
  it("accepts protected store SecretRefs", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve } = await import("node:path");
    const manifest = readFileSync(resolve(import.meta.dirname, "../openclaw.plugin.json"), "utf8");
    expect(manifest).toContain('"const": "store"');
  });
});
