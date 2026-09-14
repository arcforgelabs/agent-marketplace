import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const manifestPath = join(root, "openclaw.plugin.json");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));

manifest.skills = ["./skills"];
manifest.configContracts = {
  secretInputs: {
    paths: [
      {
        path: "privateIntegrationToken",
        ownerKind: "capability",
        expected: "string",
      },
    ],
  },
};
manifest.uiHints = {
  locationId: {
    label: "Location ID",
    help: "HighLevel sub-account location ID. This plugin stays pinned to one location.",
  },
  privateIntegrationToken: {
    label: "Private Integration Token",
    sensitive: true,
    help: "Sub-account PIT. Store it as a SecretRef; never paste it into chat, git, or shell history.",
  },
  timezone: {
    label: "Timezone",
    help: "IANA timezone for this location. Optional; no regional default. Use timestamps with explicit UTC offsets.",
  },
};

writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
