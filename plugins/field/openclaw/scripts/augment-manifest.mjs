import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const manifestPath = join(root, "openclaw.plugin.json");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));

manifest.skills = ["./skills"];
delete manifest.configContracts;
manifest.uiHints = {
  origin: {
    label: "Field origin",
    help: "Customer's Field HTTPS origin, for example https://field.example.com. No path, query, or credentials.",
    placeholder: "https://field.example.com",
  },
};
manifest.mcpServers = {
  field: {
    transport: "streamable-http",
    auth: "oauth",
    oauth: {
      scope: "catalog.read catalog.write quote.read quote.draft",
    },
    toolFilter: {
      include: ["field_*"],
    },
  },
};

writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
