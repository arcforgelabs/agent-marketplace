#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { createGhlClient } from './client.js';
import { resolveConfig } from './config.js';
import * as operations from './operations.js';

const groups = {
  status: operations.locationStatus, contacts: operations.contacts,
  notes: operations.notes, tasks: operations.tasks,
  conversations: operations.conversations, messages: operations.messages,
  opportunities: operations.opportunities, pipelines: operations.pipelines,
  custom_fields: operations.customFields, calendars: operations.calendars,
  workflows: operations.workflows, users: operations.users, tags: operations.tags,
};
async function main() {
  const [group, input] = process.argv.slice(2);
  if (!group || group === '--help') {
    console.log('ghl <group> [JSON | - for stdin]\nGroups: ' + Object.keys(groups).join(', '));
    console.log('Environment: GHL_TOKEN, GHL_LOCATION_ID, optional GHL_TIMEZONE. Never pass credentials as arguments.');
    return;
  }
  if (!Object.hasOwn(groups, group)) throw new Error('Unknown operation group. Use --help.');
  const params = JSON.parse(input === '-' ? readFileSync(0, 'utf8') : input || '{}');
  if (!params || typeof params !== 'object' || Array.isArray(params)) throw new Error('Input must be a JSON object.');
  const config = resolveConfig({privateIntegrationToken: process.env.GHL_TOKEN, locationId: process.env.GHL_LOCATION_ID, timezone: process.env.GHL_TIMEZONE});
  const result = await groups[group as keyof typeof groups](createGhlClient({token: config.token}), config, params);
  console.log(JSON.stringify({data: result}, null, 2));
}
main().catch((error) => { console.error(error.message); process.exitCode = 1; });
