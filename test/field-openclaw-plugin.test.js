import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import test from "node:test";

const pluginRoot = resolve(import.meta.dirname, "../plugins/field/openclaw");

test("OpenClaw Field package is an OAuth MCP connector", async () => {
  const pkg = JSON.parse(await readFile(join(pluginRoot, "package.json"), "utf8"));
  const manifest = JSON.parse(await readFile(join(pluginRoot, "openclaw.plugin.json"), "utf8"));
  const provenance = JSON.parse(await readFile(join(pluginRoot, "PROVENANCE.json"), "utf8"));
  assert.equal(pkg.name, "@arcforgelabs/openclaw-field");
  assert.equal(manifest.id, "arcforgelabs-field");
  assert.deepEqual(manifest.contracts.tools, ["field_connection_status"]);
  assert.equal(manifest.mcpServers.field.auth, "oauth");
  assert.equal(manifest.configSchema.properties.origin.pattern, "^https?://");
  assert.equal(manifest.configSchema.properties.tokenEnv, undefined);
  assert.equal(pkg.bin, undefined);
  assert.equal(provenance.sourcePath, "plugins/field");
  assert.match(provenance.sourceCommit, /^[a-f0-9]{40}$/);
});
