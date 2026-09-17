import { execFile, spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { access } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PLUGIN_ROOT = path.dirname(fileURLToPath(import.meta.url));
const BUNDLED_CONNECTOR_ROOT = path.join(PLUGIN_ROOT, "connector");
const REPOSITORY_CONNECTOR_ROOT = path.resolve(PLUGIN_ROOT, "../../connectors/xero");
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
  const [doctor, auth, profiles, rate, lock, mcp, workflows] = await Promise.all([
    execJson(paths.cli, ["doctor"], { cwd: paths.root, timeoutMs }),
    execJson(paths.cli, ["auth", "status"], { cwd: paths.root, timeoutMs }),
    execJson(paths.cli, ["profiles", "list"], { cwd: paths.root, timeoutMs }),
    execJson(paths.cli, ["rate", "status", "--include-cli"], { cwd: paths.root, timeoutMs }),
    execJson(paths.cli, ["lock", "status"], { cwd: paths.root, timeoutMs }),
    execJson(paths.mcp, ["status"], { cwd: paths.root, timeoutMs }),
    execJson(paths.workflows, ["self-test"], { cwd: paths.root, timeoutMs }),
  ]);
  const checks = { doctor, auth, profiles, rate, lock, mcp, workflows };
  return {
    ok: Object.values(checks).every((check) => check.ok),
    mode: "xero-openclaw-status",
    networkAccess: false,
    mutation: false,
    connectorRoot: paths.root,
    checks,
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
  },
};
