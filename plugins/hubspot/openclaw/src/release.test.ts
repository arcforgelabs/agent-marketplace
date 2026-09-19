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
  it("declares an OpenClaw floor without an upper bound", () => {
    const pkg = JSON.parse(readFileSync(resolve(import.meta.dirname, "../package.json"), "utf8"));
    expect(pkg.peerDependencies.openclaw).toBe(">=2026.9.3");
    expect(pkg.openclaw.compat.pluginApi).toBe(">=2026.9.3");
    expect(pkg.openclaw.compat.minGatewayVersion).toBe("2026.9.3");
    expect(pkg.peerDependencies.openclaw).not.toMatch("<=");
    expect(pkg.openclaw.compat.pluginApi).not.toMatch("<=");
  });
});
