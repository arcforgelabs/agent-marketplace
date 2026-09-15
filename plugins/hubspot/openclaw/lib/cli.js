#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { createHubSpotClient } from "./client.js";
import { resolveConfig } from "./config.js";
import * as op from "./operations.js";
const groups = { status: op.status, contacts: op.contacts, companies: op.companies, deals: op.deals, tickets: op.tickets, notes: op.notes, tasks: op.tasks, emails: op.emails, calls: op.calls, meetings: op.meetings, associations: op.associations, pipelines: op.pipelines, properties: op.properties, owners: op.owners, lists: op.lists, workflows: op.workflows, objects: op.objects };
async function main() { const [group, input] = process.argv.slice(2); if (!group || group === "--help") {
    console.log(`hubspot <group> [JSON | - for stdin]\nGroups: ${Object.keys(groups).join(", ")}\nEnvironment: HUBSPOT_TOKEN (required), optional HUBSPOT_PORTAL_ID, HUBSPOT_TIMEZONE. Never pass credentials as arguments.`);
    return;
} if (!Object.hasOwn(groups, group))
    throw new Error("Unknown operation group. Use --help."); const p = JSON.parse(input === "-" ? readFileSync(0, "utf8") : input || "{}"); if (!p || typeof p !== "object" || Array.isArray(p))
    throw new Error("Input must be a JSON object."); const cfg = resolveConfig({ accessToken: process.env.HUBSPOT_TOKEN, portalId: process.env.HUBSPOT_PORTAL_ID, timezone: process.env.HUBSPOT_TIMEZONE }); const data = await groups[group](createHubSpotClient({ token: cfg.token }), cfg, p); console.log(JSON.stringify({ data }, null, 2)); }
main().catch((e) => { console.error(e instanceof Error ? e.message : String(e)); process.exitCode = 1; });
