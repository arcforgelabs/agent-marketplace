import { Type, type TSchema } from "typebox";
import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";
import { createGhlClient } from "./client.js";
import { resolveConfig, type GhlPluginConfig } from "./config.js";
import * as operations from "./operations.js";

const configSchema = Type.Object(
  {
    locationId: Type.String({
      description: "HighLevel sub-account location ID. Pin this plugin to one location.",
    }),
    privateIntegrationToken: Type.Union([
      Type.String({ minLength: 1 }),
      Type.Object({ source: Type.Union([Type.Literal("env"), Type.Literal("file"), Type.Literal("exec")]), provider: Type.String(), id: Type.String() }, { additionalProperties: false }),
    ], { description: "Sub-account PIT. Use a host-managed SecretRef, never chat or source control." }),
    timezone: Type.Optional(
      Type.String({
        description: "IANA timezone for this location. Optional; no regional default. Use timestamps with explicit UTC offsets.",
      }),
    ),
  },
  { additionalProperties: false },
);

const customFields = Type.Optional(
  Type.Array(
    Type.Object(
      {
        id: Type.String(),
        value: Type.Unknown(),
      },
      { additionalProperties: false },
    ),
  ),
);

async function run(
  handler: (
    client: ReturnType<typeof createGhlClient>,
    config: ReturnType<typeof resolveConfig>,
    params: Record<string, unknown>,
  ) => Promise<unknown>,
  params: unknown,
  config: GhlPluginConfig,
  signal?: AbortSignal,
): Promise<{ data: unknown }> {
  signal?.throwIfAborted();
  const resolved = resolveConfig(config);
  const client = createGhlClient({ token: resolved.token, signal });
  const data = await handler(client, resolved, (params ?? {}) as Record<string, unknown>);
  return { data };
}

function actionSchema(values: string[], description: string): TSchema {
  return Type.Union(
    values.map((value) => Type.Literal(value)),
    { description },
  );
}

export default defineToolPlugin({
  id: "arcforgelabs-gohighlevel",
  name: "GoHighLevel by Arc Forge",
  description:
    "Unofficial HighLevel CRM tools for one sub-account: contacts, conversations, opportunities, calendars, workflows, and more.",
  configSchema,
  tools: (tool) => [
    tool({
      name: "ghl_status",
      label: "HighLevel Status",
      description: "Check that the configured HighLevel sub-account token and location are reachable.",
      parameters: Type.Object({}, { additionalProperties: false }),
      async execute(_params, config, context) {
        return run(operations.locationStatus, {}, config, context.signal);
      },
    }),
    tool({
      name: "ghl_contacts",
      label: "HighLevel Contacts",
      description:
        "Search, get, upsert, update, tag, or delete contacts in the configured HighLevel location. Upsert dedupes by email/phone.",
      parameters: Type.Object(
        {
          action: actionSchema(
            ["search", "get", "upsert", "update", "add_tags", "remove_tags", "delete"],
            "Contact operation to run.",
          ),
          contactId: Type.Optional(Type.String()),
          query: Type.Optional(Type.String()),
          email: Type.Optional(Type.String()),
          phone: Type.Optional(Type.String()),
          firstName: Type.Optional(Type.String()),
          lastName: Type.Optional(Type.String()),
          name: Type.Optional(Type.String()),
          source: Type.Optional(Type.String()),
          tags: Type.Optional(Type.Union([Type.Array(Type.String()), Type.String()])),
          address1: Type.Optional(Type.String()),
          city: Type.Optional(Type.String()),
          state: Type.Optional(Type.String()),
          postalCode: Type.Optional(Type.String()),
          country: Type.Optional(Type.String()),
          customFields,
          filters: Type.Optional(Type.Unknown()),
          page: Type.Optional(Type.Number()),
          limit: Type.Optional(Type.Number()),
          startAfter: Type.Optional(Type.String()),
          startAfterId: Type.Optional(Type.String()),
        },
        { additionalProperties: false },
      ),
      async execute(params, config, context) {
        return run(operations.contacts, params, config, context.signal);
      },
    }),
    tool({
      name: "ghl_notes",
      label: "HighLevel Notes",
      description: "List, read, create, update, or delete contact notes.",
      parameters: Type.Object(
        {
          action: actionSchema(["list", "get", "create", "update", "delete"], "Note operation to run."),
          contactId: Type.String(),
          noteId: Type.Optional(Type.String()),
          body: Type.Optional(Type.String()),
        },
        { additionalProperties: false },
      ),
      async execute(params, config, context) {
        return run(operations.notes, params, config, context.signal);
      },
    }),
    tool({
      name: "ghl_tasks",
      label: "HighLevel Tasks",
      description: "List, create, update, complete, or delete contact tasks.",
      parameters: Type.Object(
        {
          action: actionSchema(["list", "create", "update", "complete", "delete"], "Task operation to run."),
          contactId: Type.String(),
          taskId: Type.Optional(Type.String()),
          title: Type.Optional(Type.String()),
          body: Type.Optional(Type.String()),
          dueDate: Type.Optional(Type.String()),
          assignedTo: Type.Optional(Type.String()),
          completed: Type.Optional(Type.Boolean()),
        },
        { additionalProperties: false },
      ),
      async execute(params, config, context) {
        return run(operations.tasks, params, config, context.signal);
      },
    }),
    tool({
      name: "ghl_conversations",
      label: "HighLevel Conversations",
      description: "Search conversations and read SMS, email, call, and activity history for a contact.",
      parameters: Type.Object(
        {
          action: actionSchema(["search", "get", "messages"], "Conversation operation to run."),
          conversationId: Type.Optional(Type.String()),
          contactId: Type.Optional(Type.String()),
          query: Type.Optional(Type.String()),
          type: Type.Optional(Type.String()),
          lastMessageId: Type.Optional(Type.String()),
          limit: Type.Optional(Type.Number()),
        },
        { additionalProperties: false },
      ),
      async execute(params, config, context) {
        return run(operations.conversations, params, config, context.signal);
      },
    }),
    tool({
      name: "ghl_messages",
      label: "HighLevel Messages",
      description: "Send SMS or email, and fetch call recordings or transcriptions when they exist.",
      parameters: Type.Object(
        {
          action: actionSchema(["send", "recording", "transcription"], "Message operation to run."),
          contactId: Type.Optional(Type.String()),
          messageId: Type.Optional(Type.String()),
          type: Type.Optional(Type.String({ description: "SMS, Email, or another HighLevel message type." })),
          message: Type.Optional(Type.String()),
          html: Type.Optional(Type.String()),
          subject: Type.Optional(Type.String()),
          emailFrom: Type.Optional(Type.String()),
          attachments: Type.Optional(Type.Unknown()),
        },
        { additionalProperties: false },
      ),
      async execute(params, config, context) {
        return run(operations.messages, params, config, context.signal);
      },
    }),
    tool({
      name: "ghl_opportunities",
      label: "HighLevel Opportunities",
      description: "Search, get, create, or update opportunities, including stage, status, value, and assignment.",
      parameters: Type.Object(
        {
          action: actionSchema(["search", "get", "create", "update"], "Opportunity operation to run."),
          opportunityId: Type.Optional(Type.String()),
          contactId: Type.Optional(Type.String()),
          pipelineId: Type.Optional(Type.String()),
          pipelineStageId: Type.Optional(Type.String()),
          name: Type.Optional(Type.String()),
          query: Type.Optional(Type.String()),
          opportunityStatus: Type.Optional(Type.String({ description: "open, won, lost, or abandoned." })),
          monetaryValue: Type.Optional(Type.Number()),
          assignedTo: Type.Optional(Type.String()),
          source: Type.Optional(Type.String()),
          customFields,
          limit: Type.Optional(Type.Number()),
          startAfterId: Type.Optional(Type.String()),
        },
        { additionalProperties: false },
      ),
      async execute(params, config, context) {
        return run(operations.opportunities, params, config, context.signal);
      },
    }),
    tool({
      name: "ghl_pipelines",
      label: "HighLevel Pipelines",
      description: "List opportunity pipelines or create a new pipeline with ordered stages.",
      parameters: Type.Object(
        {
          action: actionSchema(["list", "create"], "Pipeline operation to run."),
          name: Type.Optional(Type.String()),
          stages: Type.Optional(Type.Union([Type.Array(Type.String()), Type.String()])),
        },
        { additionalProperties: false },
      ),
      async execute(params, config, context) {
        return run(operations.pipelines, params, config, context.signal);
      },
    }),
    tool({
      name: "ghl_custom_fields",
      label: "HighLevel Custom Fields",
      description: "List or create contact and opportunity custom fields for the configured location.",
      parameters: Type.Object(
        {
          action: actionSchema(["list", "create"], "Custom field operation to run."),
          name: Type.Optional(Type.String()),
          dataType: Type.Optional(Type.String()),
          model: Type.Optional(Type.String({ description: "contact or opportunity." })),
          options: Type.Optional(Type.Union([Type.Array(Type.String()), Type.String()])),
        },
        { additionalProperties: false },
      ),
      async execute(params, config, context) {
        return run(operations.customFields, params, config, context.signal);
      },
    }),
    tool({
      name: "ghl_calendars",
      label: "HighLevel Calendars",
      description: "List calendars, inspect free slots, and create, update, or delete appointments.",
      parameters: Type.Object(
        {
          action: actionSchema(
            [
              "list",
              "get",
              "free_slots",
              "list_events",
              "get_appointment",
              "create_appointment",
              "update_appointment",
              "delete_appointment",
            ],
            "Calendar operation to run.",
          ),
          calendarId: Type.Optional(Type.String()),
          appointmentId: Type.Optional(Type.String()),
          contactId: Type.Optional(Type.String()),
          title: Type.Optional(Type.String()),
          startTime: Type.Optional(Type.String()),
          endTime: Type.Optional(Type.String()),
          appointmentStatus: Type.Optional(Type.String()),
          assignedTo: Type.Optional(Type.String()),
          body: Type.Optional(Type.String()),
        },
        { additionalProperties: false },
      ),
      async execute(params, config, context) {
        return run(operations.calendars, params, config, context.signal);
      },
    }),
    tool({
      name: "ghl_workflows",
      label: "HighLevel Workflows",
      description:
        "List workflows and enroll or unenroll a contact. Workflow construction is not supported by this plugin.",
      parameters: Type.Object(
        {
          action: actionSchema(["list", "enroll", "unenroll"], "Workflow operation to run."),
          contactId: Type.Optional(Type.String()),
          workflowId: Type.Optional(Type.String()),
        },
        { additionalProperties: false },
      ),
      async execute(params, config, context) {
        return run(operations.workflows, params, config, context.signal);
      },
    }),
    tool({
      name: "ghl_users",
      label: "HighLevel Users",
      description: "List users in the configured HighLevel location, for assignment and ownership.",
      parameters: Type.Object(
        {
          action: actionSchema(["list"], "User operation to run."),
        },
        { additionalProperties: false },
      ),
      async execute(params, config, context) {
        return run(operations.users, params, config, context.signal);
      },
    }),
    tool({
      name: "ghl_tags",
      label: "HighLevel Tags",
      description: "List tags defined on the configured HighLevel location.",
      parameters: Type.Object(
        {
          action: actionSchema(["list"], "Tag operation to run."),
        },
        { additionalProperties: false },
      ),
      async execute(params, config, context) {
        return run(operations.tags, params, config, context.signal);
      },
    }),
  ],
});
