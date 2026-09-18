import {Type, type TSchema} from "typebox";
import {defineToolPlugin} from "openclaw/plugin-sdk/tool-plugin";
import {createFergusClient} from "./client.js";
import {resolveConfig, type FergusPluginConfig} from "./config.js";
import * as operations from "./operations.js";

const secretRef = Type.Object(
  {
    source: Type.Union([
      Type.Literal("env"),
      Type.Literal("file"),
      Type.Literal("exec"),
      Type.Literal("store"),
    ]),
    provider: Type.String(),
    id: Type.String(),
  },
  {additionalProperties: false},
);

const configSchema = Type.Object(
  {
    apiToken: Type.Union([Type.String({minLength: 1}), secretRef], {
      description:
        "Fergus company Personal Access Token. Prefer a host-managed SecretRef including source store.",
    }),
    companyId: Type.Optional(
      Type.String({
        description: "Optional company guid from GET /company. Verified on fergus_status when set.",
      }),
    ),
    maxRequestsPerMinute: Type.Optional(
      Type.Number({
        minimum: 1,
        maximum: 100,
        description: "Local governor cap. Default 80, hard-capped at the vendor 100/min company budget.",
      }),
    ),
    timezone: Type.Optional(
      Type.String({description: "Optional IANA timezone; no regional default."}),
    ),
  },
  {additionalProperties: false},
);

function actionSchema(values: string[], description: string): TSchema {
  return Type.Union(
    values.map((value) => Type.Literal(value)),
    {description},
  );
}

const paging = {
  pageSize: Type.Optional(Type.Number()),
  pageCursor: Type.Optional(Type.String()),
  sortOrder: Type.Optional(Type.String()),
  sortField: Type.Optional(Type.String()),
  filterSearchText: Type.Optional(Type.String()),
  payload: Type.Optional(Type.Unknown()),
};

async function run(
  handler: (
    client: ReturnType<typeof createFergusClient>,
    config: ReturnType<typeof resolveConfig>,
    params: Record<string, unknown>,
  ) => Promise<unknown>,
  params: unknown,
  config: FergusPluginConfig,
  signal?: AbortSignal,
): Promise<{data: unknown}> {
  signal?.throwIfAborted();
  const resolved = resolveConfig(config);
  const client = createFergusClient({
    token: resolved.token,
    signal,
    maxRequestsPerMinute: resolved.maxRequestsPerMinute,
  });
  const data = await handler(client, resolved, (params ?? {}) as Record<string, unknown>);
  return {data};
}

export default defineToolPlugin({
  id: "arcforgelabs-fergus",
  name: "Fergus by Arc Forge",
  description:
    "Unofficial Fergus trades job-management tools: jobs, quotes, calendar, customers, stock, and more. Not affiliated with Fergus.",
  configSchema,
  tools: (tool) => [
    tool({
      name: "fergus_status",
      label: "Fergus Status",
      description:
        "Read-only probe: /version, /users/me, /company, and the local 100/min company rate-limit governor.",
      parameters: Type.Object({}, {additionalProperties: false}),
      async execute(_params, config, context) {
        return run(operations.status, {}, config, context.signal);
      },
    }),
    tool({
      name: "fergus_jobs",
      label: "Fergus Jobs",
      description:
        "Jobs and phases: list/get/create/update/finalise/hold/resume/financial plus phase CRUD, void, readyForInvoice, reopen.",
      parameters: Type.Object(
        {
          action: actionSchema(
            [
              "list",
              "get",
              "create",
              "update",
              "finalise",
              "hold",
              "resume",
              "financial",
              "phases_list",
              "phases_create",
              "phase_get",
              "phase_update",
              "phase_void",
              "phase_readyForInvoice",
              "phase_reopen",
              "phase_financial",
            ],
            "Job operation to run. Writes require an explicit action; there is no default write.",
          ),
          jobId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          jobPhaseId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          jobType: Type.Optional(Type.String()),
          title: Type.Optional(Type.String()),
          description: Type.Optional(Type.String()),
          customerId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          siteId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          parentJobId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          customerReference: Type.Optional(Type.String()),
          isDraft: Type.Optional(Type.Boolean()),
          holdUntil: Type.Optional(Type.String()),
          notes: Type.Optional(Type.String()),
          filterJobNo: Type.Optional(Type.String()),
          filterJobStatus: Type.Optional(Type.String()),
          filterJobType: Type.Optional(Type.String()),
          filterCustomerId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          filterSiteId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          filterShowOnHold: Type.Optional(Type.Boolean()),
          filterShowArchived: Type.Optional(Type.Boolean()),
          filterStatus: Type.Optional(Type.String()),
          filterUpdatedSince: Type.Optional(Type.String()),
          ...paging,
        },
        {additionalProperties: false},
      ),
      async execute(params, config, context) {
        return run(operations.jobs, params, config, context.signal);
      },
    }),
    tool({
      name: "fergus_quotes",
      label: "Fergus Quotes",
      description:
        "Quotes: list/get/create/update/version plus publish, markAsSent, markAsViewed, accept, decline, void, totals.",
      parameters: Type.Object(
        {
          action: actionSchema(
            [
              "list",
              "list_for_job",
              "get",
              "get_by_guid",
              "create",
              "update",
              "update_version",
              "publish",
              "markAsSent",
              "markAsViewed",
              "accept",
              "decline",
              "void",
              "totals",
            ],
            "Quote operation to run. Writes require an explicit action.",
          ),
          jobId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          quoteId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          guid: Type.Optional(Type.String()),
          versionNumber: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          title: Type.Optional(Type.String()),
          description: Type.Optional(Type.String()),
          dueDays: Type.Optional(Type.Number()),
          sections: Type.Optional(Type.Unknown()),
          filterStatus: Type.Optional(Type.String()),
          createdAfter: Type.Optional(Type.String()),
          modifiedAfter: Type.Optional(Type.String()),
          includeCombinedItemParents: Type.Optional(Type.Boolean()),
          ...paging,
        },
        {additionalProperties: false},
      ),
      async execute(params, config, context) {
        return run(operations.quotes, params, config, context.signal);
      },
    }),
    tool({
      name: "fergus_calendar",
      label: "Fergus Calendar",
      description:
        "Calendar events: list/get/create/update/delete. Update is POST /calendarEvents/{id}. eventType JOB_PHASE | QUOTE | ESTIMATE | OTHER.",
      parameters: Type.Object(
        {
          action: actionSchema(
            ["list", "get", "create", "update", "delete"],
            "Calendar operation to run. Writes require an explicit action.",
          ),
          calendarEventId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          userId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          linkedUserIds: Type.Optional(Type.Unknown()),
          startTime: Type.Optional(Type.String()),
          endTime: Type.Optional(Type.String()),
          jobId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          jobPhaseId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          eventTitle: Type.Optional(Type.String()),
          eventType: Type.Optional(Type.String()),
          description: Type.Optional(Type.String()),
          frequency: Type.Optional(Type.String()),
          interval: Type.Optional(Type.Number()),
          repeatEndType: Type.Optional(Type.String()),
          repeatEndDate: Type.Optional(Type.String()),
          repeatCount: Type.Optional(Type.Number()),
          updateAllRecurring: Type.Optional(Type.Boolean()),
          updateAllGrouped: Type.Optional(Type.Boolean()),
          deleteOnDate: Type.Optional(Type.String()),
          deleteAllRecurring: Type.Optional(Type.Boolean()),
          deleteAllGrouped: Type.Optional(Type.Boolean()),
          filterCalendarEventType: Type.Optional(Type.String()),
          filterUserId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          filterJobId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          filterJobPhaseId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          filterJobEventsOnly: Type.Optional(Type.Boolean()),
          filterNonJobEventsOnly: Type.Optional(Type.Boolean()),
          filterUnassignedEventsOnly: Type.Optional(Type.Boolean()),
          filterActiveOnly: Type.Optional(Type.Boolean()),
          filterDateFrom: Type.Optional(Type.String()),
          filterCalendarRange: Type.Optional(Type.String()),
          ...paging,
        },
        {additionalProperties: false},
      ),
      async execute(params, config, context) {
        return run(operations.calendar, params, config, context.signal);
      },
    }),
    tool({
      name: "fergus_customers",
      label: "Fergus Customers",
      description: "Customers: list/get/create/update/delete.",
      parameters: Type.Object(
        {
          action: actionSchema(
            ["list", "get", "create", "update", "delete"],
            "Customer operation to run. Writes require an explicit action.",
          ),
          customerId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          customerFullName: Type.Optional(Type.String()),
          mainContact: Type.Optional(Type.Unknown()),
          physicalAddress: Type.Optional(Type.Unknown()),
          postalAddress: Type.Optional(Type.Unknown()),
          ...paging,
        },
        {additionalProperties: false},
      ),
      async execute(params, config, context) {
        return run(operations.customers, params, config, context.signal);
      },
    }),
    tool({
      name: "fergus_sites",
      label: "Fergus Sites",
      description: "Sites: list/get/create/update plus archive and restore.",
      parameters: Type.Object(
        {
          action: actionSchema(
            ["list", "get", "create", "update", "archive", "restore"],
            "Site operation to run. Writes require an explicit action.",
          ),
          siteId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          name: Type.Optional(Type.String()),
          defaultContact: Type.Optional(Type.Unknown()),
          billingContact: Type.Optional(Type.Unknown()),
          siteAddress: Type.Optional(Type.Unknown()),
          postalAddress: Type.Optional(Type.Unknown()),
          filterSiteName: Type.Optional(Type.String()),
          filterAddressCity: Type.Optional(Type.String()),
          filterAddressPostalCode: Type.Optional(Type.String()),
          ...paging,
        },
        {additionalProperties: false},
      ),
      async execute(params, config, context) {
        return run(operations.sites, params, config, context.signal);
      },
    }),
    tool({
      name: "fergus_contacts",
      label: "Fergus Contacts",
      description: "Customer and site contacts: list/get/create/update.",
      parameters: Type.Object(
        {
          action: actionSchema(
            ["list", "get", "create", "update"],
            "Contact operation to run. Writes require an explicit action.",
          ),
          contactId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          firstName: Type.Optional(Type.String()),
          lastName: Type.Optional(Type.String()),
          position: Type.Optional(Type.String()),
          company: Type.Optional(Type.String()),
          email: Type.Optional(Type.String()),
          contactType: Type.Optional(Type.String()),
          customerId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          siteId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          isMain: Type.Optional(Type.Boolean()),
          isBilling: Type.Optional(Type.Boolean()),
          contactItems: Type.Optional(Type.Unknown()),
          filterContactType: Type.Optional(Type.String()),
          filterCustomerId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          filterSiteId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          ...paging,
        },
        {additionalProperties: false},
      ),
      async execute(params, config, context) {
        return run(operations.contacts, params, config, context.signal);
      },
    }),
    tool({
      name: "fergus_users",
      label: "Fergus Users",
      description: "Users: list, me, get, and PATCH update.",
      parameters: Type.Object(
        {
          action: actionSchema(
            ["list", "me", "get", "update"],
            "User operation to run. Writes require an explicit action.",
          ),
          userId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          firstName: Type.Optional(Type.String()),
          lastName: Type.Optional(Type.String()),
          address: Type.Optional(Type.Unknown()),
          payRate: Type.Optional(Type.Number()),
          chargeOutRate: Type.Optional(Type.Number()),
          contactItems: Type.Optional(Type.Unknown()),
          filterUserType: Type.Optional(Type.String()),
          filterStatus: Type.Optional(Type.String()),
          ...paging,
        },
        {additionalProperties: false},
      ),
      async execute(params, config, context) {
        return run(operations.users, params, config, context.signal);
      },
    }),
    tool({
      name: "fergus_notes",
      label: "Fergus Notes",
      description:
        "Notes: list/create/update. entityName is job | customer | customer_invoice | quote | site | task | enquiry | works_order.",
      parameters: Type.Object(
        {
          action: actionSchema(
            ["list", "create", "update"],
            "Note operation to run. Writes require an explicit action.",
          ),
          noteId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          text: Type.Optional(Type.String()),
          entityName: Type.Optional(Type.String()),
          entityId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          parentId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          isPinned: Type.Optional(Type.Boolean()),
          filterEntityId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          filterEntityName: Type.Optional(Type.String()),
          filterCreatedById: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          ...paging,
        },
        {additionalProperties: false},
      ),
      async execute(params, config, context) {
        return run(operations.notes, params, config, context.signal);
      },
    }),
    tool({
      name: "fergus_tasks",
      label: "Fergus Tasks",
      description: "Tasks: list/get/create/update/delete plus complete and reopen.",
      parameters: Type.Object(
        {
          action: actionSchema(
            ["list", "get", "create", "update", "delete", "complete", "reopen"],
            "Task operation to run. Writes require an explicit action.",
          ),
          taskId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          description: Type.Optional(Type.String()),
          dueDate: Type.Optional(Type.String()),
          jobId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          assignedEmployeeIds: Type.Optional(Type.Unknown()),
          filterStatus: Type.Optional(Type.String()),
          filterEmployeeId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          filterJobId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          filterDueDateFrom: Type.Optional(Type.String()),
          filterDueDateTo: Type.Optional(Type.String()),
          filterOverdue: Type.Optional(Type.Boolean()),
          ...paging,
        },
        {additionalProperties: false},
      ),
      async execute(params, config, context) {
        return run(operations.tasks, params, config, context.signal);
      },
    }),
    tool({
      name: "fergus_files",
      label: "Fergus Files",
      description:
        "Attachments: list/upload/download/delete. form and certificate are list+download only. Download returns signed URL metadata and must not be cached.",
      parameters: Type.Object(
        {
          action: actionSchema(
            ["list", "upload", "download", "delete"],
            "File operation to run. Writes require an explicit action.",
          ),
          attachmentId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          entityType: Type.Optional(Type.String()),
          entityId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          filePath: Type.Optional(Type.String()),
          fileBase64: Type.Optional(Type.String()),
          fileName: Type.Optional(Type.String()),
          mimeType: Type.Optional(Type.String()),
          search: Type.Optional(Type.String()),
          filterMimeType: Type.Optional(Type.String()),
          filterCreatedAfter: Type.Optional(Type.String()),
          filterCreatedBefore: Type.Optional(Type.String()),
          filterCreatedById: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          ...paging,
        },
        {additionalProperties: false},
      ),
      async execute(params, config, context) {
        return run(operations.files, params, config, context.signal);
      },
    }),
    tool({
      name: "fergus_enquiries",
      label: "Fergus Enquiries",
      description: "Enquiries: list/get/create.",
      parameters: Type.Object(
        {
          action: actionSchema(
            ["list", "get", "create"],
            "Enquiry operation to run. Writes require an explicit action.",
          ),
          enquiryId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          name: Type.Optional(Type.String()),
          email: Type.Optional(Type.String()),
          phoneNumber: Type.Optional(Type.String()),
          description: Type.Optional(Type.String()),
          source: Type.Optional(Type.String()),
          address1: Type.Optional(Type.String()),
          address2: Type.Optional(Type.String()),
          addressSuburb: Type.Optional(Type.String()),
          addressCity: Type.Optional(Type.String()),
          addressRegion: Type.Optional(Type.String()),
          addressPostcode: Type.Optional(Type.String()),
          addressCountry: Type.Optional(Type.String()),
          filterStatus: Type.Optional(Type.String()),
          filterSource: Type.Optional(Type.String()),
          ...paging,
        },
        {additionalProperties: false},
      ),
      async execute(params, config, context) {
        return run(operations.enquiries, params, config, context.signal);
      },
    }),
    tool({
      name: "fergus_invoices",
      label: "Fergus Customer Invoices",
      description: "Customer invoices are GET-only: list and get. The API cannot create or send invoices.",
      parameters: Type.Object(
        {
          action: actionSchema(["list", "get"], "Invoice read operation."),
          invoiceId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          customerId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          jobId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          invoiceNumber: Type.Optional(Type.String()),
          dueBefore: Type.Optional(Type.String()),
          dueAfter: Type.Optional(Type.String()),
          filterDirectDebitStatus: Type.Optional(Type.String()),
          ...paging,
        },
        {additionalProperties: false},
      ),
      async execute(params, config, context) {
        return run(operations.invoices, params, config, context.signal);
      },
    }),
    tool({
      name: "fergus_time",
      label: "Fergus Time Entries",
      description: "Time entries are GET-only. The API cannot create time entries.",
      parameters: Type.Object(
        {
          action: actionSchema(["list"], "Time-entry read operation."),
          filterLockedOnly: Type.Optional(Type.Boolean()),
          filterUserId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          filterJobNo: Type.Optional(Type.String()),
          filterJobPhaseId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          filterDateFrom: Type.Optional(Type.String()),
          filterDateTo: Type.Optional(Type.String()),
          ...paging,
        },
        {additionalProperties: false},
      ),
      async execute(params, config, context) {
        return run(operations.timeEntries, params, config, context.signal);
      },
    }),
    tool({
      name: "fergus_stock",
      label: "Fergus Stock",
      description: "Phase stock-on-hand writes plus GET /stockUsed.",
      parameters: Type.Object(
        {
          action: actionSchema(
            ["list", "list_for_phase", "create", "update", "delete", "used"],
            "Stock operation to run. Writes require an explicit action.",
          ),
          jobPhaseId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          stockOnHandId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          itemQuantity: Type.Optional(Type.Number()),
          priceBookLineItemId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          salesAccountId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          itemDescription: Type.Optional(Type.String()),
          itemPrice: Type.Optional(Type.Number()),
          itemCost: Type.Optional(Type.Number()),
          isLabour: Type.Optional(Type.Boolean()),
          lastModified: Type.Optional(Type.String()),
          dateEntered: Type.Optional(Type.String()),
          filterDateFrom: Type.Optional(Type.String()),
          ...paging,
        },
        {additionalProperties: false},
      ),
      async execute(params, config, context) {
        return run(operations.stock, params, config, context.signal);
      },
    }),
    tool({
      name: "fergus_pricebooks",
      label: "Fergus Price Books",
      description: "Price books, search, items, and pricing tiers. Search is POST /pricebooks/search.",
      parameters: Type.Object(
        {
          action: actionSchema(
            ["search", "list", "get", "list_items", "get_item", "list_tiers", "get_tier"],
            "Price book operation to run.",
          ),
          pricebookId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          pricebookItemId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          pricingTierId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          search: Type.Optional(Type.String()),
          allSuppliers: Type.Optional(Type.Boolean()),
          supplierIds: Type.Optional(Type.Unknown()),
          filterSupplierName: Type.Optional(Type.String()),
          filterPricingTierId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          ...paging,
        },
        {additionalProperties: false},
      ),
      async execute(params, config, context) {
        return run(operations.pricebooks, params, config, context.signal);
      },
    }),
    tool({
      name: "fergus_favourites",
      label: "Fergus Favourites",
      description: "Favourites are GET-only: list folders/sections and get a section.",
      parameters: Type.Object(
        {
          action: actionSchema(["list", "get"], "Favourite read operation."),
          sectionId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
          filterSectionName: Type.Optional(Type.String()),
          representation: Type.Optional(Type.String()),
          ...paging,
        },
        {additionalProperties: false},
      ),
      async execute(params, config, context) {
        return run(operations.favourites, params, config, context.signal);
      },
    }),
  ],
});
