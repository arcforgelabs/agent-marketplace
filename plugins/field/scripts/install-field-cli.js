#!/usr/bin/env node

import process from "node:process";
import { access, chmod, copyFile, mkdir, writeFile } from "node:fs/promises";
import { constants } from "node:fs";
import { homedir } from "node:os";
import { delimiter, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

function expandHome(value) {
  if (!value) return value;
  if (value === "~") return homedir();
  if (value.startsWith("~/")) return join(homedir(), value.slice(2));
  return value;
}

async function writable(path) {
  try {
    await access(path, constants.W_OK);
    return true;
  } catch {
    try {
      await access(dirname(path), constants.W_OK);
      return true;
    } catch {
      return false;
    }
  }
}

async function choosePrefix() {
  const explicit = expandHome(process.env.FIELD_CLI_PREFIX || "");
  if (explicit) return explicit;

  const npm = process.platform === "win32" ? "npm.cmd" : "npm";
  const result = spawnSync(npm, ["config", "get", "prefix"], { encoding: "utf8" });
  const npmPrefix = expandHome(result.status === 0 ? result.stdout.trim() : "");
  if (npmPrefix && await writable(npmPrefix)) return npmPrefix;

  if (process.platform === "win32") {
    return join(process.env.LOCALAPPDATA || join(homedir(), "AppData", "Local"), "Programs", "field");
  }
  return join(homedir(), ".local");
}

function shellQuote(value) {
  return `'${String(value).replaceAll("'", `'"'"'`)}'`;
}

async function main() {
  const sourceDir = dirname(fileURLToPath(import.meta.url));
  const sourceCli = join(sourceDir, "field-cli.js");
  const prefix = await choosePrefix();
  const binDir = join(prefix, "bin");
  const runtimeDir = join(prefix, "share", "field-cli");
  const installedCli = join(runtimeDir, "field-cli.js");

  await mkdir(binDir, { recursive: true });
  await mkdir(runtimeDir, { recursive: true });
  await copyFile(sourceCli, installedCli);
  await writeFile(join(runtimeDir, "package.json"), '{"private":true,"type":"module"}\n', "utf8");

  let launcher;
  if (process.platform === "win32") {
    launcher = join(binDir, "field.cmd");
    await writeFile(launcher, `@echo off\r\nnode "${installedCli}" %*\r\n`, "utf8");
  } else {
    launcher = join(binDir, "field");
    await writeFile(launcher, `#!/bin/sh\nexec node ${shellQuote(installedCli)} "$@"\n`, { encoding: "utf8", mode: 0o755 });
    await chmod(launcher, 0o755);
  }

  console.log("Field CLI installed");
  console.log(`  launcher: ${launcher}`);
  console.log(`  runtime: ${installedCli}`);

  const pathEntries = String(process.env.PATH || "").split(delimiter).filter(Boolean);
  if (!pathEntries.includes(binDir)) {
    console.log(`  PATH note: add ${binDir} to PATH, then open a new terminal`);
  }
  console.log("Next: field auth login --url https://field.embarkearthworks.au");
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
