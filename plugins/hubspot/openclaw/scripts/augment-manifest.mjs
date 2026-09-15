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
        path: "accessToken",
        ownerKind: "capability",
        expected: "string",
      },
    ],
  },
};
manifest.uiHints = {
  accessToken: {
    label: "Private app access token",
    sensitive: true,
    help: "HubSpot private app token. Store it as a SecretRef; never paste it into chat, git, or shell history.",
  },
  portalId: {
    label: "Portal ID",
    help: "Optional HubSpot portal ID. Digits only; used as operator context, not a second credential.",
  },
  timezone: {
    label: "Timezone",
    help: "IANA timezone for this portal. Optional; no regional default.",
  },
};

writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
