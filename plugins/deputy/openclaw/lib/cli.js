#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { createDeputyClient } from "./client.js";
import { resolveConfig } from "./config.js";
import * as operations from "./operations.js";
const groups = {
    status: operations.status,
    employees: operations.employees,
    timesheets: operations.timesheets,
    leave: operations.leave,
    rosters: operations.rosters,
    locations: operations.locations,
    areas: operations.areas,
    pay: operations.pay,
};
async function main() {
    const [group, input] = process.argv.slice(2);
    if (!group || group === "--help") {
        console.log("deputy <group> [JSON | - for stdin]");
        console.log("Groups: " + Object.keys(groups).join(", "));
        console.log("Deputy does not publish a numeric rate limit. This CLI uses a process-wide local governor (default 60/min, hard-capped at 120) and honours retry-after / x-ratelimit-* when present.");
        console.log("Environment: DEPUTY_API_TOKEN and DEPUTY_INSTALL_HOST (required), optional DEPUTY_MAX_REQUESTS_PER_MINUTE, DEPUTY_TIMEZONE.");
        console.log("Never pass credentials as arguments. JSON stdout only; the token is never printed.");
        return;
    }
    if (!Object.hasOwn(groups, group))
        throw new Error("Unknown operation group. Use --help.");
    const params = JSON.parse(input === "-" ? readFileSync(0, "utf8") : input || "{}");
    if (!params || typeof params !== "object" || Array.isArray(params)) {
        throw new Error("Input must be a JSON object.");
    }
    const rpm = process.env.DEPUTY_MAX_REQUESTS_PER_MINUTE;
    const config = resolveConfig({
        apiToken: process.env.DEPUTY_API_TOKEN,
        installHost: process.env.DEPUTY_INSTALL_HOST,
        maxRequestsPerMinute: rpm ? Number(rpm) : undefined,
        timezone: process.env.DEPUTY_TIMEZONE,
    });
    const client = createDeputyClient({
        token: config.token,
        installHost: config.installHost,
        maxRequestsPerMinute: config.maxRequestsPerMinute,
    });
    const data = await groups[group](client, config, params);
    console.log(JSON.stringify({ data }, null, 2));
}
main().catch((error) => {
    console.error(error instanceof Error ? error.message : "Deputy CLI failed.");
    process.exitCode = 1;
});
