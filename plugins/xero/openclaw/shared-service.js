import { spawn } from "node:child_process";
import path from "node:path";

// The manifest's mcpServers.xero points at this loopback URL. Every OpenClaw
// session connects to the same server, so the Gateway runs one Xero backend
// chain in total instead of one stdio chain per session.
export const SHARED_PORT = 8796;
export const SHARED_HEALTH_URL = `http://127.0.0.1:${SHARED_PORT}/healthz`;

const PROBE_TIMEOUT_MS = 1500;
const RESTART_MIN_MS = 1000;
const RESTART_MAX_MS = 30000;

/** Probe the shared server. Returns its health payload, or null if nothing answers. */
export async function probeSharedService(url = SHARED_HEALTH_URL, timeoutMs = PROBE_TIMEOUT_MS) {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
    const payload = await response.json().catch(() => null);
    // 503 means "starting" or "degraded": a Xero server owns the port either way.
    return payload && payload.server === "xero" ? payload : null;
  } catch {
    return null;
  }
}

function spawnSharedServer({ connectorRoot, env, logger }) {
  const child = spawn(path.join(connectorRoot, "mcp/xero-mcp"), ["serve", "--host", "127.0.0.1", "--port", String(SHARED_PORT), "--exit-with-parent"], {
    cwd: connectorRoot,
    env,
    stdio: ["ignore", "ignore", "pipe"],
  });
  child.stderr?.setEncoding("utf8");
  child.stderr?.on("data", (chunk) => {
    for (const line of chunk.split("\n")) if (line.trim()) logger.debug?.(`[xero-mcp] ${line}`);
  });
  return child;
}

/**
 * Owner of the shared Xero MCP server on an OpenClaw Gateway.
 *
 * When nothing healthy answers on the shared port at Gateway start, this
 * service starts one gateway-owned server and restarts it if it crashes, so
 * every session shares one backend chain. Running it from the plugin keeps the
 * server on the current plugin generation after `openclaw plugins update`,
 * which a systemd unit pointing into a managed install path cannot. If an
 * operator runs the systemd unit (`xero-mcp service install`) instead, this
 * service sees it healthy and stands down.
 */
export function createSharedService({
  connectorRoot,
  env,
  autoStart = true,
  probe = probeSharedService,
  spawnServer = spawnSharedServer,
  setTimer = setTimeout,
  clearTimer = clearTimeout,
}) {
  let child = null;
  let timer = null;
  let stopping = false;
  let backoffMs = RESTART_MIN_MS;
  let ctxRef = null;

  async function ensure() {
    timer = null;
    if (stopping) return;
    const { logger, serviceHealth } = ctxRef;
    const health = await probe();
    if (stopping) return;
    if (health) {
      if (!child && health.connector_root && path.resolve(health.connector_root) !== path.resolve(connectorRoot)) {
        logger.warn(
          `Xero shared MCP server on port ${SHARED_PORT} runs connector ${health.connector_root}, not this plugin's ${connectorRoot}; restart it after plugin updates.`,
        );
      }
      serviceHealth?.clearFailure();
      return;
    }
    if (!autoStart) {
      const message = `Xero shared MCP server is not answering on 127.0.0.1:${SHARED_PORT}; start arc-forge-xero-mcp.service or enable sharedServiceAutoStart.`;
      logger.warn(message);
      serviceHealth?.reportFailure(new Error(message));
      return;
    }
    logger.info(`Xero shared MCP server not running; starting a gateway-owned instance on 127.0.0.1:${SHARED_PORT}.`);
    const started = spawnServer({ connectorRoot, env, logger });
    child = started;
    const startedAt = Date.now();
    started.once("error", (error) => logger.warn(`Xero shared MCP server failed to start: ${error.message}`));
    started.once("exit", (code, signal) => {
      if (child === started) child = null;
      if (stopping) return;
      if (Date.now() - startedAt > RESTART_MAX_MS) backoffMs = RESTART_MIN_MS;
      logger.warn(`Xero shared MCP server exited (${signal || code}); re-checking in ${backoffMs} ms.`);
      timer = setTimer(ensure, backoffMs);
      backoffMs = Math.min(backoffMs * 2, RESTART_MAX_MS);
    });
  }

  return {
    id: "xero-mcp-shared",
    // Never block Gateway startup on the probe or on backend start.
    start(ctx) {
      stopping = false;
      ctxRef = ctx;
      timer = setTimer(ensure, 0);
    },
    async stop() {
      stopping = true;
      if (timer) clearTimer(timer);
      timer = null;
      const running = child;
      child = null;
      if (running && running.exitCode === null) {
        running.kill("SIGTERM");
      }
    },
    get child() {
      return child;
    },
  };
}
