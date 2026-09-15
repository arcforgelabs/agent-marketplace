import { describe, expect, it } from "vitest"; import { readFileSync } from "node:fs"; import { resolve } from "node:path";
describe("release payload policy", () => {
  it("ships only the blank account template", () => {
    const dir = resolve(import.meta.dirname, "../skills/hubspot");
    expect(() => readFileSync(resolve(dir, "ACCOUNT.md"))).toThrow();
    expect(readFileSync(resolve(dir, "ACCOUNT.template.md"), "utf8")).toContain("Portal ID:");
  });
  it("does not publish HighLevel leftover config fields", () => {
    const manifest = readFileSync(resolve(import.meta.dirname, "../openclaw.plugin.json"), "utf8");
    expect(manifest).not.toMatch(/HighLevel|privateIntegrationToken|locationId/);
    expect(manifest).toContain('"path": "accessToken"');
    expect(manifest).toContain('"const": "store"');
    expect(manifest).toContain('"const": "env"');
  });
});
