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
        path: "apiToken",
        ownerKind: "capability",
        expected: "string",
      },
    ],
  },
};
manifest.uiHints = {
  apiToken: {
    label: "Fergus API token",
    sensitive: true,
    help: "Company Personal Access Token from Fergus account settings. Store it as a SecretRef; never paste it into chat, git, or shell history.",
  },
  companyId: {
    label: "Company ID",
    help: "Optional company guid from GET /company. When set, fergus_status verifies it matches the token's company.",
  },
  maxRequestsPerMinute: {
    label: "Max requests per minute",
    help: "Local governor cap. Default 80, hard-capped at Fergus's 100 requests per minute per company.",
  },
  timezone: {
    label: "Timezone",
    help: "IANA timezone for this company. Optional; no regional default. Use timestamps with explicit UTC offsets.",
  },
};

writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
