import type { GhlClient } from "./client.js";
import { capLimit, compact, type ResolvedGhlConfig } from "./config.js";

type Dict = Record<string, unknown>;

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function requireString(params: Dict, key: string, action: string): string {
  const value = asString(params[key]);
  if (!value) throw new Error(`${key} is required for ${action}.`);
  if ((key.endsWith("Id") || key == "noteId") && !/^[A-Za-z0-9_-]+$/.test(value)) {
    throw new Error(`Invalid ${key}.`);
  }
  return value;
}

function stringList(value: unknown): string[] | undefined {
  if (Array.isArray(value)) {
    const items = value.map((item) => String(item).trim()).filter(Boolean);
    return items.length ? items : undefined;
  }
  if (typeof value === "string" && value.trim()) {
    return value.split(",").map((item) => item.trim()).filter(Boolean);
  }
  return undefined;
}

export async function locationStatus(client: GhlClient, config: ResolvedGhlConfig, _params?: Dict) {
  const location = await client.request("GET", `/locations/${config.locationId}`);
  const record = (location as Dict).location ?? location;
  const named = record as Dict;
  return {
    connected: true,
    locationId: config.locationId,
    timezone: config.timezone ?? named.timezone ?? null,
    locationName: named.name ?? named.businessName ?? null,
  };
}

export async function contacts(client: GhlClient, config: ResolvedGhlConfig, params: Dict) {
  const action = requireString(params, "action", "ghl_contacts");
  switch (action) {
    case "search": {
      const query = asString(params.query) ?? asString(params.email) ?? asString(params.phone);
      const email = asString(params.email);
      const phone = asString(params.phone);
      if (params.filters) {
        return client.request("POST", "/contacts/search", {
          body: compact({
            locationId: config.locationId,
            page: params.page ?? 1,
            pageLimit: capLimit(params.limit as number | undefined),
            query,
            filters: params.filters,
          }),
        });
      }
      return client.request("GET", "/contacts/", {
        query: {
          locationId: config.locationId,
          query,
          limit: capLimit(params.limit as number | undefined),
          startAfter: asString(params.startAfter),
          startAfterId: asString(params.startAfterId),
        },
      });
    }
    case "get":
      return client.request("GET", `/contacts/${requireString(params, "contactId", action)}`);
    case "upsert":
      return client.request("POST", "/contacts/upsert", {
        body: compact({
          locationId: config.locationId,
          firstName: asString(params.firstName),
          lastName: asString(params.lastName),
          name: asString(params.name),
          email: asString(params.email),
          phone: asString(params.phone),
          source: asString(params.source),
          tags: stringList(params.tags),
          address1: asString(params.address1),
          city: asString(params.city),
          state: asString(params.state),
          postalCode: asString(params.postalCode),
          country: asString(params.country),
          customFields: params.customFields,
        }),
      });
    case "update":
      return client.request("PUT", `/contacts/${requireString(params, "contactId", action)}`, {
        body: compact({
          firstName: asString(params.firstName),
          lastName: asString(params.lastName),
          name: asString(params.name),
          email: asString(params.email),
          phone: asString(params.phone),
          source: asString(params.source),
          address1: asString(params.address1),
          city: asString(params.city),
          state: asString(params.state),
          postalCode: asString(params.postalCode),
          country: asString(params.country),
          customFields: params.customFields,
        }),
      });
    case "add_tags":
      return client.request("POST", `/contacts/${requireString(params, "contactId", action)}/tags`, {
        body: { tags: stringList(params.tags) ?? [] },
      });
    case "remove_tags":
      return client.request("DELETE", `/contacts/${requireString(params, "contactId", action)}/tags`, {
        body: { tags: stringList(params.tags) ?? [] },
      });
    case "delete":
      return client.request("DELETE", `/contacts/${requireString(params, "contactId", action)}`);
    default:
      throw new Error(`Unsupported contacts action: ${action}`);
  }
}

export async function notes(client: GhlClient, _config: ResolvedGhlConfig, params: Dict) {
  const action = requireString(params, "action", "ghl_notes");
  const contactId = requireString(params, "contactId", action);
  switch (action) {
    case "list":
      return client.request("GET", `/contacts/${contactId}/notes`);
    case "get":
      return client.request("GET", `/contacts/${contactId}/notes/${requireString(params, "noteId", action)}`);
    case "create":
      return client.request("POST", `/contacts/${contactId}/notes`, {
        body: { body: requireString(params, "body", action) },
      });
    case "update":
      return client.request("PUT", `/contacts/${contactId}/notes/${requireString(params, "noteId", action)}`, {
        body: { body: requireString(params, "body", action) },
      });
    case "delete":
      return client.request("DELETE", `/contacts/${contactId}/notes/${requireString(params, "noteId", action)}`);
    default:
      throw new Error(`Unsupported notes action: ${action}`);
  }
}

export async function tasks(client: GhlClient, _config: ResolvedGhlConfig, params: Dict) {
  const action = requireString(params, "action", "ghl_tasks");
  const contactId = requireString(params, "contactId", action);
  switch (action) {
    case "list":
      return client.request("GET", `/contacts/${contactId}/tasks`);
    case "create":
      return client.request("POST", `/contacts/${contactId}/tasks`, {
        body: compact({
          title: requireString(params, "title", action),
          body: asString(params.body),
          dueDate: asString(params.dueDate),
          assignedTo: asString(params.assignedTo),
          completed: params.completed,
        }),
      });
    case "update":
      return client.request("PUT", `/contacts/${contactId}/tasks/${requireString(params, "taskId", action)}`, {
        body: compact({
          title: asString(params.title),
          body: asString(params.body),
          dueDate: asString(params.dueDate),
          assignedTo: asString(params.assignedTo),
          completed: params.completed,
        }),
      });
    case "complete":
      return client.request(
        "PUT",
        `/contacts/${contactId}/tasks/${requireString(params, "taskId", action)}/completed`,
        { body: { completed: params.completed ?? true } },
      );
    case "delete":
      return client.request("DELETE", `/contacts/${contactId}/tasks/${requireString(params, "taskId", action)}`);
    default:
      throw new Error(`Unsupported tasks action: ${action}`);
  }
}

export async function conversations(client: GhlClient, config: ResolvedGhlConfig, params: Dict) {
  const action = requireString(params, "action", "ghl_conversations");
  switch (action) {
    case "search":
      return client.request("GET", "/conversations/search", {
        query: {
          locationId: config.locationId,
          contactId: asString(params.contactId),
          query: asString(params.query),
          limit: capLimit(params.limit as number | undefined),
          lastMessageId: asString(params.lastMessageId),
        },
      });
    case "get":
      return client.request("GET", `/conversations/${requireString(params, "conversationId", action)}`);
    case "messages":
      return client.request("GET", `/conversations/${requireString(params, "conversationId", action)}/messages`, {
        query: {
          limit: capLimit(params.limit as number | undefined),
          lastMessageId: asString(params.lastMessageId),
          type: asString(params.type),
        },
      });
    default:
      throw new Error(`Unsupported conversations action: ${action}`);
  }
}

export async function messages(client: GhlClient, config: ResolvedGhlConfig, params: Dict) {
  const action = requireString(params, "action", "ghl_messages");
  switch (action) {
    case "send": {
      const type = requireString(params, "type", action);
      return client.request("POST", "/conversations/messages", {
        body: compact({
          type,
          contactId: requireString(params, "contactId", action),
          message: asString(params.message),
          html: asString(params.html),
          subject: asString(params.subject),
          emailFrom: asString(params.emailFrom),
          attachments: params.attachments,
        }),
      });
    }
    case "recording":
      return client.request(
        "GET",
        `/conversations/messages/${requireString(params, "messageId", action)}/locations/${config.locationId}/recording`,
      );
    case "transcription":
      return client.request(
        "GET",
        `/conversations/locations/${config.locationId}/messages/${requireString(params, "messageId", action)}/transcription`,
      );
    default:
      throw new Error(`Unsupported messages action: ${action}`);
  }
}

export async function opportunities(client: GhlClient, config: ResolvedGhlConfig, params: Dict) {
  const action = requireString(params, "action", "ghl_opportunities");
  switch (action) {
    case "search":
      return client.request("GET", "/opportunities/search", {
        query: {
          location_id: config.locationId,
          q: asString(params.query),
          contact_id: asString(params.contactId),
          pipeline_id: asString(params.pipelineId),
          pipeline_stage_id: asString(params.pipelineStageId),
          status: asString(params.opportunityStatus),
          limit: capLimit(params.limit as number | undefined),
          startAfterId: asString(params.startAfterId),
        },
      });
    case "get":
      return client.request("GET", `/opportunities/${requireString(params, "opportunityId", action)}`);
    case "create":
      return client.request("POST", "/opportunities/", {
        body: compact({
          locationId: config.locationId,
          pipelineId: requireString(params, "pipelineId", action),
          pipelineStageId: requireString(params, "pipelineStageId", action),
          contactId: requireString(params, "contactId", action),
          name: requireString(params, "name", action),
          status: asString(params.opportunityStatus) ?? "open",
          monetaryValue: params.monetaryValue,
          assignedTo: asString(params.assignedTo),
          source: asString(params.source),
          customFields: params.customFields,
        }),
      });
    case "update":
      return client.request("PUT", `/opportunities/${requireString(params, "opportunityId", action)}`, {
        body: compact({
          pipelineId: asString(params.pipelineId),
          pipelineStageId: asString(params.pipelineStageId),
          contactId: asString(params.contactId),
          name: asString(params.name),
          status: asString(params.opportunityStatus),
          monetaryValue: params.monetaryValue,
          assignedTo: asString(params.assignedTo),
          source: asString(params.source),
          customFields: params.customFields,
        }),
      });
    default:
      throw new Error(`Unsupported opportunities action: ${action}`);
  }
}

export async function pipelines(client: GhlClient, config: ResolvedGhlConfig, params: Dict) {
  const action = requireString(params, "action", "ghl_pipelines");
  switch (action) {
    case "list":
      return client.request("GET", "/opportunities/pipelines", {
        query: { locationId: config.locationId },
      });
    case "create": {
      const names = stringList(params.stages) ?? [];
      if (!names.length) throw new Error("stages is required for pipeline create.");
      const stages = names.map((name, index) => ({
        name,
        position: index,
        showInFunnel: true,
        showInPieChart: true,
      }));
      return client.request("POST", "/opportunities/pipelines", {
        body: {
          locationId: config.locationId,
          name: requireString(params, "name", action),
          stages,
        },
      });
    }
    default:
      throw new Error(`Unsupported pipelines action: ${action}`);
  }
}

export async function customFields(client: GhlClient, config: ResolvedGhlConfig, params: Dict) {
  const action = requireString(params, "action", "ghl_custom_fields");
  switch (action) {
    case "list":
      return client.request("GET", `/locations/${config.locationId}/customFields`, {
        query: { model: asString(params.model) },
      });
    case "create":
      return client.request("POST", `/locations/${config.locationId}/customFields`, {
        body: compact({
          name: requireString(params, "name", action),
          dataType: asString(params.dataType) ?? "TEXT",
          model: asString(params.model) ?? "contact",
          options: stringList(params.options),
        }),
      });
    default:
      throw new Error(`Unsupported custom_fields action: ${action}`);
  }
}

export async function calendars(client: GhlClient, config: ResolvedGhlConfig, params: Dict) {
  const action = requireString(params, "action", "ghl_calendars");
  switch (action) {
    case "list":
      return client.request("GET", "/calendars/", {
        query: { locationId: config.locationId },
      });
    case "get":
      return client.request("GET", `/calendars/${requireString(params, "calendarId", action)}`);
    case "free_slots":
      return client.request("GET", `/calendars/${requireString(params, "calendarId", action)}/free-slots`, {
        query: {
          startDate: asString(params.startTime),
          endDate: asString(params.endTime),
        },
      });
    case "list_events":
      return client.request("GET", "/calendars/events", {
        query: {
          locationId: config.locationId,
          calendarId: asString(params.calendarId),
          startTime: asString(params.startTime),
          endTime: asString(params.endTime),
        },
      });
    case "get_appointment":
      return client.request(
        "GET",
        `/calendars/events/appointments/${requireString(params, "appointmentId", action)}`,
      );
    case "create_appointment":
      return client.request("POST", "/calendars/events/appointments", {
        body: compact({
          locationId: config.locationId,
          calendarId: requireString(params, "calendarId", action),
          contactId: requireString(params, "contactId", action),
          startTime: requireString(params, "startTime", action),
          endTime: asString(params.endTime),
          title: asString(params.title),
          appointmentStatus: asString(params.appointmentStatus),
          assignedUserId: asString(params.assignedTo),
          notes: asString(params.body),
        }),
      });
    case "update_appointment":
      return client.request(
        "PUT",
        `/calendars/events/appointments/${requireString(params, "appointmentId", action)}`,
        {
          body: compact({
            calendarId: asString(params.calendarId),
            contactId: asString(params.contactId),
            startTime: asString(params.startTime),
            endTime: asString(params.endTime),
            title: asString(params.title),
            appointmentStatus: asString(params.appointmentStatus),
            assignedUserId: asString(params.assignedTo),
            notes: asString(params.body),
          }),
        },
      );
    case "delete_appointment":
      return client.request("DELETE", `/calendars/events/${requireString(params, "appointmentId", action)}`);
    default:
      throw new Error(`Unsupported calendars action: ${action}`);
  }
}

export async function workflows(client: GhlClient, config: ResolvedGhlConfig, params: Dict) {
  const action = requireString(params, "action", "ghl_workflows");
  switch (action) {
    case "list":
      return client.request("GET", "/workflows/", {
        query: { locationId: config.locationId },
      });
    case "enroll":
      return client.request(
        "POST",
        `/contacts/${requireString(params, "contactId", action)}/workflow/${requireString(params, "workflowId", action)}`,
      );
    case "unenroll":
      return client.request(
        "DELETE",
        `/contacts/${requireString(params, "contactId", action)}/workflow/${requireString(params, "workflowId", action)}`,
      );
    default:
      throw new Error(`Unsupported workflows action: ${action}`);
  }
}

export async function users(client: GhlClient, config: ResolvedGhlConfig, params: Dict) {
  const action = requireString(params, "action", "ghl_users");
  if (action !== "list") throw new Error(`Unsupported users action: ${action}`);
  return client.request("GET", "/users/", {
    query: { locationId: config.locationId },
  });
}

export async function tags(client: GhlClient, config: ResolvedGhlConfig, params: Dict) {
  const action = requireString(params, "action", "ghl_tags");
  if (action !== "list") throw new Error(`Unsupported tags action: ${action}`);
  return client.request("GET", `/locations/${config.locationId}/tags`);
}
