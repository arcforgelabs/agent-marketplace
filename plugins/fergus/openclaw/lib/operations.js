import { readFile } from "node:fs/promises";
import { basename } from "node:path";
import { capLimit, compact } from "./config.js";
const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;
const WRITABLE_FILE_ENTITIES = new Set(["customer", "job", "site", "enquiry", "job_phase"]);
const FILE_ENTITIES = new Set(["customer", "job", "site", "enquiry", "job_phase", "form", "certificate"]);
const NOTE_ENTITIES = new Set(["job", "customer", "customer_invoice", "quote", "site", "task", "enquiry", "works_order"]);
const JOB_TYPES = new Set(["Quote", "Estimate", "Charge Up"]);
const EVENT_TYPES = new Set(["JOB_PHASE", "QUOTE", "ESTIMATE", "OTHER"]);
function asString(value) {
    if (typeof value === "number" && Number.isFinite(value))
        return String(value);
    return typeof value === "string" && value.trim() ? value.trim() : undefined;
}
function requiredAction(params, tool) {
    const action = typeof params.action === "string" ? params.action.trim() : "";
    if (!action)
        throw new Error(`action is required for ${tool}; mutating calls must set it explicitly.`);
    return action;
}
function requireString(params, key, action) {
    const value = asString(params[key]);
    if (!value)
        throw new Error(`${key} is required for ${action}.`);
    return value;
}
function id(params, key, action) {
    const value = asString(params[key]);
    if (!value)
        throw new Error(`${key} is required for ${action}.`);
    if (!/^\d+$/.test(value))
        throw new Error(`Invalid ${key}.`);
    return value;
}
function optionalId(params, key) {
    const value = asString(params[key]);
    if (!value)
        return undefined;
    if (!/^\d+$/.test(value))
        throw new Error(`Invalid ${key}.`);
    return value;
}
function guid(params, action) {
    const value = requireString(params, "guid", action);
    if (!/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/.test(value)) {
        throw new Error("Invalid guid.");
    }
    return value;
}
function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
function payloadOf(params, fields) {
    const extra = isPlainObject(params.payload) ? params.payload : {};
    const picked = { ...extra };
    for (const field of fields) {
        if (params[field] !== undefined)
            picked[field] = params[field];
    }
    return compact(picked);
}
function queryOf(params, keys) {
    const query = {};
    for (const key of keys) {
        const value = params[key];
        if (value === undefined || value === null || value === "")
            continue;
        if (typeof value === "number" || typeof value === "boolean")
            query[key] = value;
        else
            query[key] = String(value);
    }
    if (params.pageSize !== undefined)
        query.pageSize = capLimit(params.pageSize, 10, 100);
    return query;
}
const PAGE_KEYS = [
    "pageSize",
    "pageCursor",
    "sortOrder",
    "sortField",
    "filterSearchText",
];
function unwrap(record) {
    if (!isPlainObject(record))
        return {};
    return isPlainObject(record.data) ? record.data : record;
}
export async function status(client, config, _params = {}) {
    const [version, me, company] = await Promise.all([
        client.request("GET", "/version"),
        client.request("GET", "/users/me"),
        client.request("GET", "/company"),
    ]);
    const companyData = unwrap(company);
    const companyGuid = asString(companyData.guid) ?? asString(companyData.id);
    if (config.companyId && companyGuid && config.companyId !== companyGuid) {
        throw new Error("Configured companyId does not match /company guid.");
    }
    const meData = unwrap(me);
    return {
        connected: true,
        companyId: config.companyId ?? companyGuid ?? null,
        companyName: companyData.name ?? companyData.prefix ?? null,
        companyGuid: companyGuid ?? null,
        userId: meData.id ?? null,
        userEmail: meData.email ?? null,
        timezone: config.timezone ?? null,
        version,
        rateLimit: client.governor.snapshot(),
    };
}
export async function jobs(client, _config, params) {
    const action = requiredAction(params, "fergus_jobs");
    switch (action) {
        case "list":
            return client.request("GET", "/jobs", {
                query: queryOf(params, [
                    ...PAGE_KEYS,
                    "filterJobNo",
                    "filterJobStatus",
                    "filterJobType",
                    "filterCustomerId",
                    "filterSiteId",
                    "filterShowOnHold",
                    "filterShowArchived",
                ]),
            });
        case "get":
            return client.request("GET", `/jobs/${id(params, "jobId", action)}`);
        case "create": {
            const body = payloadOf(params, [
                "isDraft",
                "jobType",
                "title",
                "description",
                "customerId",
                "customerReference",
                "siteId",
                "parentJobId",
            ]);
            if (body.jobType !== undefined && !JOB_TYPES.has(String(body.jobType))) {
                throw new Error("jobType must be Quote, Estimate, or Charge Up.");
            }
            return client.request("POST", "/jobs", { body });
        }
        case "update":
            return client.request("PUT", `/jobs/${id(params, "jobId", action)}`, {
                body: payloadOf(params, ["title", "description", "customerId", "customerReference", "siteId"]),
            });
        case "finalise":
            return client.request("PUT", `/jobs/${id(params, "jobId", action)}/finalise`);
        case "hold":
            return client.request("POST", `/jobs/${id(params, "jobId", action)}/hold`, {
                body: payloadOf(params, ["holdUntil", "notes"]),
            });
        case "resume":
            return client.request("POST", `/jobs/${id(params, "jobId", action)}/resume`);
        case "financial":
            return client.request("GET", `/jobs/${id(params, "jobId", action)}/financialSummary`);
        case "phases_list":
            return client.request("GET", `/jobs/${id(params, "jobId", action)}/phases`, {
                query: queryOf(params, ["filterStatus", "filterUpdatedSince"]),
            });
        case "phases_create":
            return client.request("POST", `/jobs/${id(params, "jobId", action)}/phases`, {
                body: payloadOf(params, ["title", "description"]),
            });
        case "phase_get":
            return client.request("GET", `/jobs/${id(params, "jobId", action)}/phases/${id(params, "jobPhaseId", action)}`);
        case "phase_update":
            return client.request("PUT", `/jobs/${id(params, "jobId", action)}/phases/${id(params, "jobPhaseId", action)}`, { body: payloadOf(params, ["title", "description"]) });
        case "phase_void":
            return client.request("POST", `/jobs/${id(params, "jobId", action)}/phases/${id(params, "jobPhaseId", action)}/void`);
        case "phase_readyForInvoice":
            return client.request("POST", `/jobs/${id(params, "jobId", action)}/phases/${id(params, "jobPhaseId", action)}/readyForInvoice`);
        case "phase_reopen":
            return client.request("POST", `/jobs/${id(params, "jobId", action)}/phases/${id(params, "jobPhaseId", action)}/reopen`);
        case "phase_financial":
            return client.request("GET", `/jobs/${id(params, "jobId", action)}/phases/${id(params, "jobPhaseId", action)}/financialSummary`);
        default:
            throw new Error(`Unsupported jobs action: ${action}`);
    }
}
export async function quotes(client, _config, params) {
    const action = requiredAction(params, "fergus_quotes");
    switch (action) {
        case "list":
            return client.request("GET", "/jobs/quotes", {
                query: queryOf(params, [...PAGE_KEYS, "filterStatus", "createdAfter", "modifiedAfter"]),
            });
        case "list_for_job":
            return client.request("GET", `/jobs/${id(params, "jobId", action)}/quotes`, {
                query: queryOf(params, [...PAGE_KEYS, "includeCombinedItemParents", "filterStatus"]),
            });
        case "get": {
            const jobId = optionalId(params, "jobId");
            const quoteId = id(params, "quoteId", action);
            return jobId
                ? client.request("GET", `/jobs/${jobId}/quotes/${quoteId}`)
                : client.request("GET", `/jobs/quotes/${quoteId}`);
        }
        case "get_by_guid":
            return client.request("GET", `/jobs/quotes/guid/${guid(params, action)}`, {
                query: queryOf(params, ["includeCombinedItemParents"]),
            });
        case "create":
            return client.request("POST", `/jobs/${id(params, "jobId", action)}/quotes`, {
                body: payloadOf(params, ["title", "description", "dueDays", "versionNumber", "sections"]),
            });
        case "update":
            return client.request("PUT", `/jobs/${id(params, "jobId", action)}/quotes/${id(params, "quoteId", action)}`, { body: payloadOf(params, ["title", "description", "sections"]) });
        case "update_version":
            return client.request("PUT", `/jobs/${id(params, "jobId", action)}/quotes/version/${id(params, "versionNumber", action)}`, { body: payloadOf(params, ["title", "description", "sections"]) });
        case "publish":
            return client.request("POST", `/jobs/quotes/${id(params, "quoteId", action)}/publish`, {
                body: payloadOf(params, ["publishedAt", "publishedBy"]),
            });
        case "markAsSent":
            return client.request("POST", `/jobs/quotes/${id(params, "quoteId", action)}/markAsSent`, {
                body: payloadOf(params, ["isSent"]),
            });
        case "markAsViewed":
            return client.request("POST", `/jobs/quotes/${id(params, "quoteId", action)}/markAsViewed`);
        case "accept":
            return client.request("POST", `/jobs/quotes/${id(params, "quoteId", action)}/accept`, {
                body: payloadOf(params, ["acceptedBy", "acceptedAt", "selectedSectionIds", "source"]),
            });
        case "decline":
            return client.request("POST", `/jobs/quotes/${id(params, "quoteId", action)}/decline`, {
                body: payloadOf(params, ["declinedAt", "reasonNotes", "rejectedBy", "source"]),
            });
        case "void":
            return client.request("POST", `/jobs/quotes/${id(params, "quoteId", action)}/void`, {
                body: payloadOf(params, ["voidedAt"]),
            });
        case "totals":
            return client.request("POST", `/jobs/quotes/${id(params, "quoteId", action)}/totals`, {
                body: payloadOf(params, ["selectedSectionIds"]),
            });
        default:
            throw new Error(`Unsupported quotes action: ${action}`);
    }
}
export async function calendar(client, _config, params) {
    const action = requiredAction(params, "fergus_calendar");
    switch (action) {
        case "list":
            return client.request("GET", "/calendarEvents", {
                query: queryOf(params, [
                    "filterCalendarEventType",
                    "filterUserId",
                    "filterJobId",
                    "filterJobPhaseId",
                    "filterJobEventsOnly",
                    "filterNonJobEventsOnly",
                    "filterUnassignedEventsOnly",
                    "filterActiveOnly",
                    "filterDateFrom",
                    "filterCalendarRange",
                ]),
            });
        case "get":
            return client.request("GET", `/calendarEvents/${id(params, "calendarEventId", action)}`);
        case "create": {
            const body = payloadOf(params, [
                "userId",
                "linkedUserIds",
                "startTime",
                "endTime",
                "jobId",
                "jobPhaseId",
                "eventTitle",
                "eventType",
                "description",
                "frequency",
                "interval",
                "repeatEndType",
                "repeatEndDate",
                "repeatCount",
            ]);
            if (body.eventType !== undefined && !EVENT_TYPES.has(String(body.eventType))) {
                throw new Error("eventType must be JOB_PHASE, QUOTE, ESTIMATE, or OTHER.");
            }
            return client.request("POST", "/calendarEvents", { body });
        }
        case "update":
            return client.request("POST", `/calendarEvents/${id(params, "calendarEventId", action)}`, {
                body: payloadOf(params, [
                    "startTime",
                    "endTime",
                    "eventTitle",
                    "description",
                    "userId",
                    "linkedUserIds",
                    "frequency",
                    "interval",
                    "repeatEndType",
                    "repeatEndDate",
                    "repeatCount",
                    "repeatSplitOnDate",
                    "updateAllRecurring",
                    "updateAllGrouped",
                ]),
            });
        case "delete":
            return client.request("DELETE", `/calendarEvents/${id(params, "calendarEventId", action)}`, {
                body: payloadOf(params, ["deleteOnDate", "deleteAllRecurring", "deleteAllGrouped"]),
            });
        default:
            throw new Error(`Unsupported calendar action: ${action}`);
    }
}
export async function customers(client, _config, params) {
    const action = requiredAction(params, "fergus_customers");
    switch (action) {
        case "list":
            return client.request("GET", "/customers", { query: queryOf(params, PAGE_KEYS) });
        case "get":
            return client.request("GET", `/customers/${id(params, "customerId", action)}`);
        case "create":
            return client.request("POST", "/customers", {
                body: payloadOf(params, ["customerFullName", "mainContact", "physicalAddress", "postalAddress"]),
            });
        case "update":
            return client.request("PUT", `/customers/${id(params, "customerId", action)}`, {
                body: payloadOf(params, ["customerFullName", "mainContact", "physicalAddress", "postalAddress"]),
            });
        case "delete":
            return client.request("DELETE", `/customers/${id(params, "customerId", action)}`);
        default:
            throw new Error(`Unsupported customers action: ${action}`);
    }
}
export async function sites(client, _config, params) {
    const action = requiredAction(params, "fergus_sites");
    switch (action) {
        case "list":
            return client.request("GET", "/sites", {
                query: queryOf(params, [...PAGE_KEYS, "filterSiteName", "filterAddressCity", "filterAddressPostalCode"]),
            });
        case "get":
            return client.request("GET", `/sites/${id(params, "siteId", action)}`);
        case "create":
            return client.request("POST", "/sites", {
                body: payloadOf(params, ["name", "defaultContact", "billingContact", "siteAddress", "postalAddress"]),
            });
        case "update":
            return client.request("PATCH", `/sites/${id(params, "siteId", action)}`, {
                body: payloadOf(params, ["name", "siteAddress", "postalAddress"]),
            });
        case "archive":
            return client.request("POST", `/sites/${id(params, "siteId", action)}/archive`);
        case "restore":
            return client.request("POST", `/sites/${id(params, "siteId", action)}/restore`);
        default:
            throw new Error(`Unsupported sites action: ${action}`);
    }
}
export async function contacts(client, _config, params) {
    const action = requiredAction(params, "fergus_contacts");
    switch (action) {
        case "list":
            return client.request("GET", "/contacts", {
                query: queryOf(params, [...PAGE_KEYS, "filterContactType", "filterCustomerId", "filterSiteId"]),
            });
        case "get":
            return client.request("GET", `/contacts/${id(params, "contactId", action)}`);
        case "create":
            return client.request("POST", "/contacts", {
                body: payloadOf(params, [
                    "firstName",
                    "lastName",
                    "position",
                    "company",
                    "contactItems",
                    "email",
                    "isMain",
                    "isBilling",
                    "siteId",
                    "customerId",
                    "contactType",
                ]),
            });
        case "update":
            return client.request("PUT", `/contacts/${id(params, "contactId", action)}`, {
                body: payloadOf(params, [
                    "firstName",
                    "lastName",
                    "position",
                    "company",
                    "contactItems",
                    "email",
                    "isMain",
                    "isBilling",
                    "siteId",
                    "customerId",
                    "contactType",
                ]),
            });
        default:
            throw new Error(`Unsupported contacts action: ${action}`);
    }
}
export async function users(client, _config, params) {
    const action = requiredAction(params, "fergus_users");
    switch (action) {
        case "list":
            return client.request("GET", "/users", {
                query: queryOf(params, [...PAGE_KEYS, "filterUserType", "filterStatus"]),
            });
        case "me":
            return client.request("GET", "/users/me");
        case "get":
            return client.request("GET", `/users/${id(params, "userId", action)}`);
        case "update":
            return client.request("PATCH", `/users/${id(params, "userId", action)}`, {
                body: payloadOf(params, ["firstName", "lastName", "address", "payRate", "chargeOutRate", "contactItems"]),
            });
        default:
            throw new Error(`Unsupported users action: ${action}`);
    }
}
export async function notes(client, _config, params) {
    const action = requiredAction(params, "fergus_notes");
    switch (action) {
        case "list":
            return client.request("GET", "/notes", {
                query: queryOf(params, [...PAGE_KEYS, "filterEntityId", "filterEntityName", "filterCreatedById"]),
            });
        case "create": {
            const entityName = requireString(params, "entityName", action);
            if (!NOTE_ENTITIES.has(entityName))
                throw new Error("Invalid entityName.");
            return client.request("POST", "/notes", {
                body: payloadOf(params, ["text", "entityName", "entityId", "parentId", "isPinned"]),
            });
        }
        case "update":
            return client.request("PATCH", `/notes/${id(params, "noteId", action)}`, {
                body: payloadOf(params, ["text", "isPinned"]),
            });
        default:
            throw new Error(`Unsupported notes action: ${action}`);
    }
}
export async function tasks(client, _config, params) {
    const action = requiredAction(params, "fergus_tasks");
    switch (action) {
        case "list":
            return client.request("GET", "/tasks", {
                query: queryOf(params, [
                    ...PAGE_KEYS,
                    "filterStatus",
                    "filterEmployeeId",
                    "filterJobId",
                    "filterDueDateFrom",
                    "filterDueDateTo",
                    "filterOverdue",
                ]),
            });
        case "get":
            return client.request("GET", `/tasks/${id(params, "taskId", action)}`);
        case "create":
            return client.request("POST", "/tasks", {
                body: payloadOf(params, ["description", "dueDate", "jobId", "assignedEmployeeIds"]),
            });
        case "update":
            return client.request("PATCH", `/tasks/${id(params, "taskId", action)}`, {
                body: payloadOf(params, ["description", "dueDate", "assignedEmployeeIds"]),
            });
        case "delete":
            return client.request("DELETE", `/tasks/${id(params, "taskId", action)}`);
        case "complete":
            return client.request("POST", `/tasks/${id(params, "taskId", action)}/complete`);
        case "reopen":
            return client.request("POST", `/tasks/${id(params, "taskId", action)}/reopen`);
        default:
            throw new Error(`Unsupported tasks action: ${action}`);
    }
}
function assertLocalFilePath(filePath) {
    if (filePath.includes("\0") ||
        filePath.includes("://") ||
        /(^|[/\\])\.\.([/\\]|$)/.test(filePath)) {
        throw new Error("Invalid filePath.");
    }
}
export async function files(client, _config, params) {
    const action = requiredAction(params, "fergus_files");
    switch (action) {
        case "list": {
            const entityType = requireString(params, "entityType", action);
            if (!FILE_ENTITIES.has(entityType))
                throw new Error("Invalid entityType.");
            return client.request("GET", "/attachments", {
                query: queryOf(params, [
                    ...PAGE_KEYS,
                    "entityType",
                    "entityId",
                    "search",
                    "filterMimeType",
                    "filterCreatedAfter",
                    "filterCreatedBefore",
                    "filterCreatedById",
                ]),
            });
        }
        case "upload": {
            const entityType = requireString(params, "entityType", action);
            if (!WRITABLE_FILE_ENTITIES.has(entityType)) {
                throw new Error("form and certificate attachments are list and download only; upload is not supported.");
            }
            const entityId = id(params, "entityId", action);
            const fileName = asString(params.fileName) ?? "upload.bin";
            if (fileName.includes("..") || fileName.includes("/") || fileName.includes("\\")) {
                throw new Error("Invalid fileName.");
            }
            let bytes;
            const filePath = asString(params.filePath);
            const fileBase64 = asString(params.fileBase64);
            if (filePath) {
                assertLocalFilePath(filePath);
                bytes = await readFile(filePath);
            }
            else if (fileBase64) {
                bytes = Buffer.from(fileBase64, "base64");
            }
            else {
                throw new Error("filePath or fileBase64 is required for upload.");
            }
            if (bytes.byteLength > MAX_UPLOAD_BYTES)
                throw new Error("Attachment exceeds the 20MB Fergus limit.");
            const form = new FormData();
            const mime = asString(params.mimeType) ?? "application/octet-stream";
            const copy = new ArrayBuffer(bytes.byteLength);
            new Uint8Array(copy).set(bytes);
            form.append("file", new Blob([copy], { type: mime }), filePath ? basename(filePath) : fileName);
            form.append("entityType", entityType);
            form.append("entityId", entityId);
            return client.request("POST", "/attachments", { form });
        }
        case "download":
            return client.download(`/attachments/${id(params, "attachmentId", action)}/download`);
        case "delete":
            return client.request("DELETE", `/attachments/${id(params, "attachmentId", action)}`);
        default:
            throw new Error(`Unsupported files action: ${action}`);
    }
}
export async function enquiries(client, _config, params) {
    const action = requiredAction(params, "fergus_enquiries");
    switch (action) {
        case "list":
            return client.request("GET", "/enquiries", {
                query: queryOf(params, [...PAGE_KEYS, "filterStatus", "filterSource"]),
            });
        case "get":
            return client.request("GET", `/enquiries/${id(params, "enquiryId", action)}`);
        case "create":
            return client.request("POST", "/enquiries", {
                body: payloadOf(params, [
                    "name",
                    "email",
                    "phoneNumber",
                    "description",
                    "source",
                    "address1",
                    "address2",
                    "addressSuburb",
                    "addressCity",
                    "addressRegion",
                    "addressPostcode",
                    "addressCountry",
                ]),
            });
        default:
            throw new Error(`Unsupported enquiries action: ${action}`);
    }
}
export async function invoices(client, _config, params) {
    const action = requiredAction(params, "fergus_invoices");
    switch (action) {
        case "list":
            return client.request("GET", "/customerInvoices", {
                query: queryOf(params, [
                    ...PAGE_KEYS,
                    "customerId",
                    "jobId",
                    "invoiceNumber",
                    "dueBefore",
                    "dueAfter",
                    "filterDirectDebitStatus",
                ]),
            });
        case "get":
            return client.request("GET", `/customerInvoices/${id(params, "invoiceId", action)}`);
        default:
            throw new Error(`Unsupported invoices action: ${action}. Customer invoices are GET-only.`);
    }
}
export async function timeEntries(client, _config, params) {
    const action = requiredAction(params, "fergus_time");
    if (action !== "list")
        throw new Error("Time entries are GET-only; use action list.");
    return client.request("GET", "/timeEntries", {
        query: queryOf(params, [
            ...PAGE_KEYS,
            "filterLockedOnly",
            "filterUserId",
            "filterJobNo",
            "filterJobPhaseId",
            "filterDateFrom",
            "filterDateTo",
        ]),
    });
}
export async function stock(client, _config, params) {
    const action = requiredAction(params, "fergus_stock");
    switch (action) {
        case "list":
            return client.request("GET", "/phases/stockOnHand", {
                query: queryOf(params, [...PAGE_KEYS, "lastModified", "dateEntered"]),
            });
        case "list_for_phase":
            return client.request("GET", `/phases/${id(params, "jobPhaseId", action)}/stockOnHand`, {
                query: queryOf(params, [...PAGE_KEYS, "lastModified", "dateEntered"]),
            });
        case "create":
            return client.request("POST", `/phases/${id(params, "jobPhaseId", action)}/stockOnHand`, {
                body: payloadOf(params, [
                    "itemQuantity",
                    "priceBookLineItemId",
                    "salesAccountId",
                    "itemDescription",
                    "itemPrice",
                    "itemCost",
                    "isLabour",
                ]),
            });
        case "update":
            return client.request("PATCH", `/phases/${id(params, "jobPhaseId", action)}/stockOnHand/${id(params, "stockOnHandId", action)}`, {
                body: payloadOf(params, [
                    "itemDescription",
                    "itemPrice",
                    "itemCost",
                    "itemQuantity",
                    "salesAccountId",
                    "isLabour",
                ]),
            });
        case "delete":
            return client.request("DELETE", `/phases/${id(params, "jobPhaseId", action)}/stockOnHand/${id(params, "stockOnHandId", action)}`);
        case "used":
            return client.request("GET", "/stockUsed", {
                query: queryOf(params, ["filterDateFrom", "pageCursor"]),
            });
        default:
            throw new Error(`Unsupported stock action: ${action}`);
    }
}
export async function pricebooks(client, _config, params) {
    const action = requiredAction(params, "fergus_pricebooks");
    switch (action) {
        case "search":
            return client.request("POST", "/pricebooks/search", {
                query: queryOf(params, PAGE_KEYS),
                body: payloadOf(params, ["search", "pricingTierId", "allSuppliers", "supplierIds"]),
            });
        case "list":
            return client.request("GET", "/pricebooks", {
                query: queryOf(params, [...PAGE_KEYS, "filterSupplierName"]),
            });
        case "get":
            return client.request("GET", `/pricebooks/${id(params, "pricebookId", action)}`);
        case "list_items":
            return client.request("GET", `/pricebooks/${id(params, "pricebookId", action)}/pricebookItems`, {
                query: queryOf(params, PAGE_KEYS),
            });
        case "get_item":
            return client.request("GET", `/pricebooks/${id(params, "pricebookId", action)}/pricebookItems/${id(params, "pricebookItemId", action)}`, { query: queryOf(params, ["filterPricingTierId"]) });
        case "list_tiers":
            return client.request("GET", "/pricingTiers", { query: queryOf(params, PAGE_KEYS) });
        case "get_tier":
            return client.request("GET", `/pricingTiers/${id(params, "pricingTierId", action)}`);
        default:
            throw new Error(`Unsupported pricebooks action: ${action}`);
    }
}
export async function favourites(client, _config, params) {
    const action = requiredAction(params, "fergus_favourites");
    switch (action) {
        case "list":
            return client.request("GET", "/favourites", {
                query: queryOf(params, [...PAGE_KEYS, "filterSectionName", "representation"]),
            });
        case "get":
            return client.request("GET", `/favourites/${id(params, "sectionId", action)}`);
        default:
            throw new Error(`Unsupported favourites action: ${action}. Favourites are GET-only.`);
    }
}
/** Kept on the client for tests; omitted from the default operator tool list. */
export async function disconnect(client, _config, params) {
    return client.request("POST", "/disconnect", {
        body: payloadOf(params, ["refreshToken", "clientId", "clientSecret"]),
    });
}
