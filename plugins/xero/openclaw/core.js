import { execFile, spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { access, mkdir, mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { SHARED_HEALTH_URL, createSharedService, probeSharedService } from "./shared-service.js";

const PLUGIN_ROOT = path.dirname(fileURLToPath(import.meta.url));
const BUNDLED_CONNECTOR_ROOT = path.join(PLUGIN_ROOT, "connector");
const REPOSITORY_CONNECTOR_ROOT = path.resolve(PLUGIN_ROOT, "../../connectors/xero");
// Agent-facing results stay inline: no tool accepts or returns a Gateway host path.
export const MAX_ATTACHMENT_DOWNLOAD_BYTES = 4 * 1024 * 1024;
export const DEFAULT_AUDIT_RECORDS = 200;
export const MAX_AUDIT_RECORDS = 1000;
const HOST_PATH_PARAMS = ["out_path", "out", "path", "file"];
const SECRET_KEY_PATTERN = /(access.?token|refresh.?token|id.?token|authorization|client.?secret|cookie|mfa|totp|password)/i;
const SECRET_ENV_NAMES = new Set([
  "XERO_ACCESS_TOKEN",
  "XERO_REFRESH_TOKEN",
  "XERO_ID_TOKEN",
  "XERO_CLIENT_SECRET",
  "XERO_CLIENT_BEARER_TOKEN",
  "ARC_FORGE_XERO_ACCESS_TOKEN",
  "ARC_FORGE_XERO_REFRESH_TOKEN",
]);

export function connectorRoot(config = {}) {
  if (config.connectorRoot) return path.resolve(config.connectorRoot);
  if (existsSync(BUNDLED_CONNECTOR_ROOT)) return BUNDLED_CONNECTOR_ROOT;
  return REPOSITORY_CONNECTOR_ROOT;
}

export function childEnvironment(source = process.env) {
  const env = { ...source };
  for (const name of SECRET_ENV_NAMES) delete env[name];
  return env;
}

export function redact(value, key = "") {
  if (SECRET_KEY_PATTERN.test(key)) {
    if (key === "client_secret_required") return value;
    return value == null ? value : "[redacted]";
  }
  if (Array.isArray(value)) return value.map((item) => redact(item));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([childKey, childValue]) => [childKey, redact(childValue, childKey)]));
  }
  if (typeof value === "string") {
    return value
      .replace(/Bearer\s+[A-Za-z0-9._~+\/-]+/gi, "Bearer [redacted]")
      .replace(/([?&](?:token|session|code)=)[^&#\s]+/gi, "$1[redacted]");
  }
  return value;
}

function execJson(file, args, options = {}) {
  return new Promise((resolve) => {
    execFile(
      file,
      args,
      {
        cwd: options.cwd,
        env: childEnvironment(options.env),
        timeout: options.timeoutMs,
        maxBuffer: 4 * 1024 * 1024,
        encoding: "utf8",
      },
      (error, stdout, stderr) => {
        let payload = null;
        try {
          payload = stdout.trim() ? JSON.parse(stdout) : null;
        } catch {
          payload = stdout.trim() ? { output: stdout.trim() } : null;
        }
        resolve({
          ok: !error,
          exitCode: typeof error?.code === "number" ? error.code : error ? 1 : 0,
          signal: error?.signal || null,
          payload: redact(payload),
          stderr: stderr.trim() ? redact(stderr.trim()) : null,
        });
      },
    );
  });
}

function pathsFor(config = {}) {
  const root = connectorRoot(config);
  return {
    root,
    cli: path.join(root, "cli/xero"),
    mcp: path.join(root, "mcp/xero-mcp-local"),
    workflows: path.join(root, "mcp/xero-workflows-mcp"),
  };
}

async function assertConnector(paths) {
  await Promise.all([access(paths.cli), access(paths.mcp), access(paths.workflows)]);
}

export async function readStatus(config = {}) {
  const paths = pathsFor(config);
  const timeoutMs = config.commandTimeoutMs || 30000;
  try {
    await assertConnector(paths);
  } catch {
    return {
      ok: false,
      mode: "xero-openclaw-status",
      connectorRoot: paths.root,
      error: "Xero connector entrypoints are missing. Configure plugins.entries.xero.config.connectorRoot.",
    };
  }
  const [doctor, auth, rate, lock, mcp, workflows] = await Promise.all([
    execJson(paths.cli, ["doctor"], { cwd: paths.root, timeoutMs }),
    execJson(paths.cli, ["auth", "status"], { cwd: paths.root, timeoutMs }),
    execJson(paths.cli, ["rate", "status", "--include-cli"], { cwd: paths.root, timeoutMs }),
    execJson(paths.cli, ["lock", "status"], { cwd: paths.root, timeoutMs }),
    execJson(paths.mcp, ["status"], { cwd: paths.root, timeoutMs }),
    execJson(paths.workflows, ["self-test"], { cwd: paths.root, timeoutMs }),
  ]);
  const checks = { doctor, auth, rate, lock, mcp, workflows };
  const shared = await probeSharedService();
  return {
    ok: Object.values(checks).every((check) => check.ok),
    mode: "xero-openclaw-status",
    networkAccess: false,
    mutation: false,
    connectorRoot: paths.root,
    checks,
    sharedService: {
      url: SHARED_HEALTH_URL,
      running: Boolean(shared),
      status: shared?.status || "down",
      sessions: shared?.sessions ?? null,
      backends: shared?.backends?.map(({ label, status, restarts }) => ({ label, status, restarts })) ?? [],
    },
  };
}

export async function readOauthContract(config = {}) {
  const paths = pathsFor(config);
  const timeoutMs = config.commandTimeoutMs || 30000;
  try {
    await access(paths.cli);
  } catch {
    return {
      ok: false,
      mode: "xero-openclaw-oauth-contract",
      error: "Xero CLI is missing. Configure plugins.entries.xero.config.connectorRoot.",
    };
  }
  const contract = await execJson(paths.cli, ["auth", "app-config"], { cwd: paths.root, timeoutMs });
  return {
    ok: contract.ok,
    mode: "xero-openclaw-oauth-contract",
    networkAccess: false,
    mutation: false,
    protectedSecretFlow: {
      staticSecretInputs: [],
      publicClientIdIsSecret: false,
      loginCredentialsEnteredAt: "Xero-hosted browser only",
      rotatingOauthTokens: "connector-managed encrypted local token store; never plugin config or environment",
      openclawSecretRequestRequired: false,
    },
    contract,
  };
}

export async function readLocalTenants(config = {}) {
  const paths = pathsFor(config);
  const timeoutMs = config.commandTimeoutMs || 30000;
  try {
    await access(paths.cli);
  } catch {
    return {
      ok: false,
      mode: "xero-openclaw-tenants-local",
      error: "Xero CLI is missing. Configure plugins.entries.xero.config.connectorRoot.",
    };
  }
  const tenants = await execJson(paths.cli, ["tenants", "list"], { cwd: paths.root, timeoutMs });
  return {
    ok: tenants.ok,
    mode: "xero-openclaw-tenants-local",
    networkAccess: false,
    mutation: false,
    tenants,
  };
}

function oauthPendingDir() {
  const override = String(process.env.ARC_FORGE_XERO_OAUTH_PENDING_DIR || "").trim();
  return override
    ? path.resolve(override)
    : path.join(os.homedir(), ".config", "arc-forge-tools", "xero", "oauth-pending");
}

function oauthCallbackHtml() {
  return "<!doctype html><meta charset=\"utf-8\"><title>Xero</title><p>Xero authorization captured. You can close this tab.</p>";
}

async function handleOAuthCallback(req, res) {
  if (req.method !== "GET") {
    res.statusCode = 405;
    res.setHeader("Content-Type", "text/plain; charset=utf-8");
    res.end("Method not allowed");
    return true;
  }
  const url = new URL(req.url || "/", "http://127.0.0.1");
  const state = url.searchParams.get("state") || "";
  if (!/^[A-Za-z0-9_-]{8,128}$/.test(state)) {
    res.statusCode = 400;
    res.setHeader("Content-Type", "text/plain; charset=utf-8");
    res.end("Missing or invalid OAuth state.");
    return true;
  }
  const directory = oauthPendingDir();
  const expectPath = path.join(directory, `${state}.expect`);
  const callbackPath = path.join(directory, `${state}.json`);
  if (!existsSync(expectPath)) {
    res.statusCode = 404;
    res.setHeader("Content-Type", "text/plain; charset=utf-8");
    res.end("No pending Xero login matches this callback.");
    return true;
  }
  const payload = {
    state,
    code: url.searchParams.get("code") || "",
    error: url.searchParams.get("error") || "",
    error_description: url.searchParams.get("error_description") || "",
  };
  await mkdir(directory, { recursive: true, mode: 0o700 });
  await writeFile(callbackPath, `${JSON.stringify(payload)}\n`, { encoding: "utf8", mode: 0o600 });
  res.statusCode = 200;
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.end(oauthCallbackHtml());
  return true;
}

export async function runCliJson(config = {}, args = []) {
  const paths = pathsFor(config);
  const timeoutMs = config.commandTimeoutMs || 30000;
  await access(paths.cli);
  return execJson(paths.cli, args, { cwd: paths.root, timeoutMs });
}

function rejectHostPaths(params) {
  const named = HOST_PATH_PARAMS.filter((name) => params[name] !== undefined);
  if (!named.length) return null;
  return {
    ok: false,
    error: `${named.join(", ")} is not accepted: agent tools return content inline and never read or write Gateway host paths. Operators can use the xero CLI --out option.`,
  };
}

async function downloadAttachment(config, params) {
  if (!params.filename) {
    return { ok: false, error: "download requires filename." };
  }
  // The plugin owns this private directory; the agent never names a host path.
  const directory = await mkdtemp(path.join(os.tmpdir(), "arcforge-xero-attachment-"));
  try {
    const target = path.join(directory, "attachment");
    const args = ["evidence", "attachments", "download", params.kind, params.object_id, params.filename, "--out", target];
    const result = await runCliJson({ ...config, commandTimeoutMs: config.commandTimeoutMs || 120000 }, args);
    if (!result.ok) return result;
    const { size } = await stat(target);
    const { out: _privatePath, ...payload } = result.payload || {};
    const summary = {
      ok: true,
      kind: params.kind,
      object_id: params.object_id,
      tenant_id: payload.tenant_id,
      filename: payload.filename || params.filename,
      content_type: payload.content_type || "application/octet-stream",
      byte_count: size,
      max_bytes: MAX_ATTACHMENT_DOWNLOAD_BYTES,
    };
    if (size > MAX_ATTACHMENT_DOWNLOAD_BYTES) {
      return {
        ...summary,
        ok: false,
        error: `Attachment is ${size} bytes, over the ${MAX_ATTACHMENT_DOWNLOAD_BYTES}-byte inline limit. An operator can fetch it with: xero evidence attachments download ${params.kind} <object_id> <filename> --out <path>.`,
      };
    }
    return { ...summary, encoding: "base64", content_base64: (await readFile(target)).toString("base64") };
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

export async function runEvidenceAttachments(config = {}, params = {}) {
  const rejected = rejectHostPaths(params);
  if (rejected) return rejected;
  const action = params.action;
  const kind = params.kind;
  const objectId = params.object_id;
  if (!action || !kind || !objectId) {
    return { ok: false, error: "action, kind, and object_id are required." };
  }
  if (action === "list") {
    const args = ["evidence", "attachments", "list", kind, objectId];
    return runCliJson(config, args);
  }
  if (action === "download") return downloadAttachment(config, params);
  return { ok: false, error: "action must be list or download." };
}

function auditRecordLimit(value) {
  if (!Number.isInteger(value)) return DEFAULT_AUDIT_RECORDS;
  return Math.min(Math.max(value, 1), MAX_AUDIT_RECORDS);
}

export async function runEvidenceAudit(config = {}, params = {}) {
  const rejected = rejectHostPaths(params);
  if (rejected) return rejected;
  const args = ["evidence", "audit"];
  const kinds = Array.isArray(params.kinds) && params.kinds.length ? params.kinds : ["bill"];
  args.push("--kinds", ...kinds);
  const result = await runCliJson({ ...config, commandTimeoutMs: config.commandTimeoutMs || 120000 }, args);
  const report = result.payload;
  if (!result.ok || !report || typeof report !== "object") return result;
  // Keep totals and per-kind counts; bound only the record lists returned inline.
  const limit = auditRecordLimit(params.max_records);
  const bounded = { ...report, max_records: limit, truncated: false };
  for (const key of ["missing_current", "missing_frozen"]) {
    const records = Array.isArray(report[key]) ? report[key] : [];
    bounded[key] = records.slice(0, limit);
    bounded[`${key}_count`] = records.length;
    if (records.length > limit) bounded.truncated = true;
  }
  return { ...result, payload: bounded };
}

function gatewayHandler(run) {
  return async ({ respond }) => {
    try {
      respond(true, await run());
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      respond(false, { error: redact(message) });
    }
  };
}

function registerGateway(api, config) {
  api.registerGatewayMethod("xero.status", gatewayHandler(() => readStatus(config)), { scope: "operator.read" });
  api.registerGatewayMethod("xero.oauth.contract", gatewayHandler(() => readOauthContract(config)), { scope: "operator.read" });
  api.registerGatewayMethod("xero.tenants.local", gatewayHandler(() => readLocalTenants(config)), { scope: "operator.read" });
}

function registerCli(api, config) {
  api.registerCli(
    async ({ program }) => {
      program
        .command("xero")
        .description("Run the Arc Forge Xero connector CLI")
        .allowUnknownOption(true)
        .allowExcessArguments(true)
        .passThroughOptions()
        .argument("[args...]", "Arguments passed unchanged to the Xero CLI")
        .action(async (args = []) => {
          const paths = pathsFor(config);
          await access(paths.cli);
          const code = await new Promise((resolve, reject) => {
            const child = spawn(paths.cli, args, {
              cwd: paths.root,
              env: childEnvironment(),
              stdio: "inherit",
            });
            child.once("error", reject);
            child.once("exit", (exitCode, signal) => resolve(exitCode ?? (signal ? 1 : 0)));
          });
          if (code !== 0) process.exitCode = code;
        });
    },
    {
      descriptors: [
        {
          name: "xero",
          description: "Run the Arc Forge Xero connector CLI",
          hasSubcommands: true,
          machineOutput: () => true,
        },
      ],
    },
  );
}

export default {
  id: "xero",
  name: "Xero",
  description: "Native OpenClaw Gateway bridge for the Arc Forge Xero connector.",
  register(api) {
    const config = api.pluginConfig || {};
    registerGateway(api, config);
    registerCli(api, config);
    if (typeof api.registerService === "function") {
      api.registerService(
        createSharedService({
          connectorRoot: connectorRoot(config),
          env: childEnvironment(),
          autoStart: config.sharedServiceAutoStart !== false,
        }),
      );
    }
    api.registerHttpRoute({
      path: "/xero/oauth/callback",
      auth: "plugin",
      match: "exact",
      handler: handleOAuthCallback,
    });
  },
};
