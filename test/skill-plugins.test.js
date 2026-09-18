import assert from "node:assert/strict";
import { readdir, readFile, stat } from "node:fs/promises";
import { join, resolve } from "node:path";
import test from "node:test";

const repoRoot = resolve(import.meta.dirname, "..");
const pluginsRoot = join(repoRoot, "plugins");

async function exists(path) {
  return stat(path).then(() => true, () => false);
}

// Generic skill plugins are staged by arc-forge-tools `forge-tools skills stage`.
// Every plugin whose PROVENANCE.json says kind=skill must be a complete,
// consistently versioned payload listed in all three marketplace manifests.
test("staged skill plugins are complete and listed for every host", async () => {
  const manifests = {};
  for (const [host, rel] of [["codex", ".agents/plugins/marketplace.json"], ["claude", ".claude-plugin/marketplace.json"], ["cursor", ".cursor-plugin/marketplace.json"]]) {
    manifests[host] = JSON.parse(await readFile(join(repoRoot, rel), "utf8")).plugins.map((p) => p.name);
  }
  let count = 0;
  for (const name of await readdir(pluginsRoot)) {
    const root = join(pluginsRoot, name);
    const provPath = join(root, "PROVENANCE.json");
    if (!(await exists(provPath))) continue;
    const prov = JSON.parse(await readFile(provPath, "utf8"));
    if (prov.kind !== "skill") continue;
    count += 1;
    assert.equal(prov.sourcePath, `components/skills/${name}`, `${name} provenance path`);
    assert.ok(await exists(join(root, "skills", name, "SKILL.md")), `${name} SKILL.md`);
    const frontmatter = (await readFile(join(root, "skills", name, "SKILL.md"), "utf8")).match(/^---\n([\s\S]*?)\n---/);
    assert.ok(frontmatter && /^name:\s*"?/m.test(frontmatter[1]) && /^description:/m.test(frontmatter[1]), `${name} frontmatter`);
    for (const hostDir of [".codex-plugin", ".claude-plugin", ".cursor-plugin"]) {
      const manifest = JSON.parse(await readFile(join(root, hostDir, "plugin.json"), "utf8"));
      assert.equal(manifest.name, name, `${name} ${hostDir} name`);
      assert.equal(manifest.version, prov.version, `${name} ${hostDir} version`);
    }
    for (const [host, names] of Object.entries(manifests)) {
      assert.ok(names.includes(name), `${name} missing from ${host} marketplace manifest`);
    }
    for (const [rel, hash] of Object.entries(prov.files)) {
      assert.ok(await exists(join(root, rel)), `${name} provenance file ${rel}`);
    }
  }
  assert.ok(count >= 1, "at least one staged skill plugin");
});
