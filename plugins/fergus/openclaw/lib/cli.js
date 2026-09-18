#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { createFergusClient } from "./client.js";
import { resolveConfig } from "./config.js";
import * as operations from "./operations.js";
const groups = {
    status: operations.status,
    jobs: operations.jobs,
    quotes: operations.quotes,
    calendar: operations.calendar,
    customers: operations.customers,
    sites: operations.sites,
    contacts: operations.contacts,
    users: operations.users,
    notes: operations.notes,
    tasks: operations.tasks,
    files: operations.files,
    enquiries: operations.enquiries,
    invoices: operations.invoices,
    time: operations.timeEntries,
    stock: operations.stock,
    pricebooks: operations.pricebooks,
    favourites: operations.favourites,
};
async function main() {
    const [group, input] = process.argv.slice(2);
    if (!group || group === "--help") {
        console.log("fergus <group> [JSON | - for stdin]");
        console.log("Groups: " + Object.keys(groups).join(", "));
        console.log("Fergus vendor limit: 100 requests per minute per company, shared across tokens and endpoints.");
        console.log("This CLI uses a process-wide local governor (default 80/min, hard-capped at 100). Do not parallel-spray list calls.");
        console.log("Environment: FERGUS_API_TOKEN (required), optional FERGUS_COMPANY_ID, FERGUS_MAX_REQUESTS_PER_MINUTE, FERGUS_TIMEZONE.");
        console.log("Never pass credentials as arguments. JSON stdout only; the token is never printed.");
        return;
    }
    if (!Object.hasOwn(groups, group))
        throw new Error("Unknown operation group. Use --help.");
    const params = JSON.parse(input === "-" ? readFileSync(0, "utf8") : input || "{}");
    if (!params || typeof params !== "object" || Array.isArray(params)) {
        throw new Error("Input must be a JSON object.");
    }
    const rpm = process.env.FERGUS_MAX_REQUESTS_PER_MINUTE;
    const config = resolveConfig({
        apiToken: process.env.FERGUS_API_TOKEN,
        companyId: process.env.FERGUS_COMPANY_ID,
        maxRequestsPerMinute: rpm ? Number(rpm) : undefined,
        timezone: process.env.FERGUS_TIMEZONE,
    });
    const client = createFergusClient({
        token: config.token,
        maxRequestsPerMinute: config.maxRequestsPerMinute,
    });
    const data = await groups[group](client, config, params);
    console.log(JSON.stringify({ data }, null, 2));
}
main().catch((error) => {
    console.error(error instanceof Error ? error.message : "Fergus CLI failed.");
    process.exitCode = 1;
});
