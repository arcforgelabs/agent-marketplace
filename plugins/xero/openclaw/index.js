import { Type } from "typebox";
import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";

import xeroCore, { readStatus } from "./core.js";

const plugin = defineToolPlugin({
  id: "arcforgelabs-xero",
  name: "Xero",
  description: "Native OpenClaw Gateway bridge for the Arc Forge Xero connector.",
  activation: {
    onStartup: true,
    onCommands: ["xero"],
  },
  configSchema: Type.Object(
    {
      connectorRoot: Type.Optional(
        Type.String({ description: "Absolute path to connectors/xero when outside the repository layout." }),
      ),
      commandTimeoutMs: Type.Optional(
        Type.Integer({ minimum: 1000, maximum: 120000, default: 30000 }),
      ),
    },
    { additionalProperties: false },
  ),
  tools: (tool) => [
    tool({
      name: "xero_status",
      label: "Xero status",
      description: "Read local Xero connector, OAuth, tenant-profile, rate-limit, lock, and MCP readiness without network access or mutation.",
      parameters: Type.Object({}, { additionalProperties: false }),
      execute: async (_params, config) => readStatus(config),
    }),
  ],
});

const registerTool = plugin.register.bind(plugin);
plugin.register = (api) => {
  registerTool(api);
  xeroCore.register(api);
};

export default plugin;
