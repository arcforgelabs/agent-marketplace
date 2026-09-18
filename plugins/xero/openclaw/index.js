import { Type } from "typebox";
import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";

import xeroCore, { readStatus, runEvidenceAttachments, runEvidenceAudit } from "./core.js";

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
    tool({
      name: "xero_evidence_attachments",
      label: "Xero bill attachments",
      description: "List or download the original uploaded file on a Xero bill/invoice (PDF/JPEG), not Xero's generated invoice PDF. Use for OCR.",
      parameters: Type.Object(
        {
          action: Type.Union([Type.Literal("list"), Type.Literal("download")]),
          kind: Type.Union([
            Type.Literal("bill"),
            Type.Literal("invoice"),
            Type.Literal("credit-note"),
            Type.Literal("quote"),
            Type.Literal("contact"),
            Type.Literal("bank-transaction"),
            Type.Literal("bank-transfer"),
            Type.Literal("manual-journal"),
            Type.Literal("purchase-order"),
          ]),
          object_id: Type.String({ description: "Xero object UUID. For bills this is InvoiceID." }),
          filename: Type.Optional(Type.String()),
          out_path: Type.Optional(Type.String({ description: "Local path to write the downloaded file." })),
          tenant_id: Type.Optional(Type.String()),
        },
        { additionalProperties: false },
      ),
      execute: async (params, config) => runEvidenceAttachments(config, params),
    }),
    tool({
      name: "xero_evidence_audit",
      label: "Xero attachment audit",
      description: "Read-only sweep of which bills/invoices lack a stapled source document.",
      parameters: Type.Object(
        {
          kinds: Type.Optional(Type.Array(Type.Union([Type.Literal("bill"), Type.Literal("invoice"), Type.Literal("bank-transaction")]))),
          out_path: Type.Optional(Type.String()),
          tenant_id: Type.Optional(Type.String()),
        },
        { additionalProperties: false },
      ),
      execute: async (params, config) => runEvidenceAudit(config, params),
    }),
  ],
});

const registerTool = plugin.register.bind(plugin);
plugin.register = (api) => {
  registerTool(api);
  xeroCore.register(api);
};

export default plugin;
