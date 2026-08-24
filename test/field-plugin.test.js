import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";

const repoRoot = resolve(import.meta.dirname, "..");
const pluginRoot = join(repoRoot, "plugins", "field");
const installer = join(pluginRoot, "scripts", "install-field-cli.js");
const TEST_TOKEN = `field_${"a".repeat(43)}`;

test("marketplace manifests expose Arc Forge / Field across all supported hosts", async () => {
  const manifests = [
    ["Codex", ".agents/plugins/marketplace.json"],
    ["Claude Code", ".claude-plugin/marketplace.json"],
    ["Cursor", ".cursor-plugin/marketplace.json"],
  ];
  for (const [host, relativePath] of manifests) {
    const manifest = JSON.parse(await readFile(join(repoRoot, relativePath), "utf8"));
    assert.equal(manifest.name, "arc-forge", `${host} marketplace name`);
    assert.equal(manifest.plugins.length, 1, `${host} plugin count`);
    assert.equal(manifest.plugins[0].name, "field", `${host} Field entry`);
  }

  for (const hostDir of [".codex-plugin", ".claude-plugin", ".cursor-plugin"]) {
    const manifest = JSON.parse(await readFile(join(pluginRoot, hostDir, "plugin.json"), "utf8"));
    assert.equal(manifest.name, "field");
    assert.equal(manifest.version, "0.1.0");
  }
});

test("bundled Field CLI installs and authenticates without exposing its token", async (t) => {
  const tempRoot = await mkdtemp(join(tmpdir(), "field-plugin-"));
  const prefix = join(tempRoot, "prefix");
  const configDir = join(tempRoot, "config");
  t.after(() => rm(tempRoot, { recursive: true, force: true }));

  const install = await run(process.execPath, [installer], {
    env: { ...process.env, FIELD_CLI_PREFIX: prefix },
  });
  const launcher = process.platform === "win32"
    ? join(prefix, "bin", "field.cmd")
    : join(prefix, "bin", "field");
  assert.match(install.stdout, /Field CLI installed/);
  assert.match((await run(launcher, ["--help"])).stdout, /email-templates/);

  const server = createServer((request, response) => {
    response.setHeader("Content-Type", "application/json");
    if (request.url === "/api/auth/me" && request.headers.authorization === `Bearer ${TEST_TOKEN}`) {
      response.end(JSON.stringify({ ok: true, user: { name: "Field Plugin Test", kind: "service" } }));
      return;
    }
    response.statusCode = 401;
    response.end(JSON.stringify({ error: "unauthorized" }));
  });
  await new Promise((resolveListen) => server.listen(0, "127.0.0.1", resolveListen));
  t.after(() => new Promise((resolveClose) => server.close(resolveClose)));

  const url = `http://127.0.0.1:${server.address().port}`;
  const login = await run(launcher, ["auth", "login", "--token-stdin", "--url", url], {
    env: { ...process.env, FIELD_CONFIG_DIR: configDir },
    input: `${TEST_TOKEN}\n`,
  });
  assert.match(login.stdout, /Authenticated as Field Plugin Test/);
  assert.doesNotMatch(login.stdout, new RegExp(TEST_TOKEN));
  assert.equal((await readFile(join(configDir, "token"), "utf8")).trim(), TEST_TOKEN);
  if (process.platform !== "win32") {
    assert.equal((await stat(join(configDir, "token"))).mode & 0o777, 0o600);
  }
});

function run(command, args, { env = process.env, input = "" } = {}) {
  return new Promise((resolveRun, rejectRun) => {
    const child = spawn(command, args, { cwd: repoRoot, env, shell: process.platform === "win32" });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", rejectRun);
    child.on("close", (code) => {
      if (code === 0) resolveRun({ stdout, stderr });
      else rejectRun(new Error(`${command} failed (${code}): ${stderr || stdout}`));
    });
    child.stdin.end(input);
  });
}
