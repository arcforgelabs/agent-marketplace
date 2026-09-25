import { Type } from "typebox";
import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";
import { createDeputyClient } from "./client.js";
import { resolveConfig } from "./config.js";
import * as operations from "./operations.js";
const secretRef = Type.Object({
    source: Type.Union([
        Type.Literal("env"),
        Type.Literal("file"),
        Type.Literal("exec"),
        Type.Literal("store"),
    ]),
    provider: Type.String(),
    id: Type.String(),
}, { additionalProperties: false });
const configSchema = Type.Object({
    apiToken: Type.Union([Type.String({ minLength: 1 }), secretRef], {
        description: "Deputy permanent API token. Prefer a host-managed SecretRef including source store.",
    }),
    installHost: Type.String({
        description: "Tenant host only, for example acme.au.deputy.com. Rejects once.deputy.com, schemes, ports, and paths.",
    }),
    maxRequestsPerMinute: Type.Optional(Type.Number({
        minimum: 1,
        maximum: 120,
        description: "Local governor cap. Default 60, hard-capped at 120. Deputy does not publish a numeric rate limit.",
    })),
    timezone: Type.Optional(Type.String({ description: "Optional IANA timezone; no regional default." })),
}, { additionalProperties: false });
function actionSchema(values, description) {
    return Type.Union(values.map((value) => Type.Literal(value)), { description });
}
const queryPaging = {
    start: Type.Optional(Type.Number()),
    max: Type.Optional(Type.Number()),
    sort: Type.Optional(Type.Unknown()),
    join: Type.Optional(Type.Unknown()),
    payload: Type.Optional(Type.Unknown()),
};
async function run(handler, params, config, signal) {
    signal?.throwIfAborted();
    const resolved = resolveConfig(config);
    const client = createDeputyClient({
        token: resolved.token,
        installHost: resolved.installHost,
        signal,
        maxRequestsPerMinute: resolved.maxRequestsPerMinute,
    });
    const data = await handler(client, resolved, (params ?? {}));
    return { data };
}
export default defineToolPlugin({
    id: "arcforgelabs-deputy",
    name: "Deputy by Arc Forge",
    description: "Unofficial Deputy payroll and workforce tools: employees, timesheets, leave, rosters, locations, and pay reads. Not affiliated with Deputy.",
    configSchema,
    tools: (tool) => [
        tool({
            name: "deputy_status",
            label: "Deputy Status",
            description: "Read-only probe: GET /v1/me, GET /v1/resource/Company, and the local unpublished-limit governor snapshot.",
            parameters: Type.Object({}, { additionalProperties: false }),
            async execute(_params, config, context) {
                return run(operations.status, {}, config, context.signal);
            },
        }),
        tool({
            name: "deputy_employees",
            label: "Deputy Employees",
            description: "Employees: list/get/create/update plus terminate, reactivate, invite, add/remove company, and resource QUERY. Advanced TFN/confidential payroll identity is a named gap.",
            parameters: Type.Object({
                action: actionSchema([
                    "list",
                    "get",
                    "create",
                    "update",
                    "terminate",
                    "reactivate",
                    "invite",
                    "add_location",
                    "remove_location",
                    "query",
                ], "Employee operation to run. Writes require an explicit action; there is no default write."),
                employeeId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
                companyId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
                strFirstName: Type.Optional(Type.String()),
                strLastName: Type.Optional(Type.String()),
                intCompanyId: Type.Optional(Type.Number()),
                intGender: Type.Optional(Type.Number()),
                strCountryCode: Type.Optional(Type.String()),
                strDob: Type.Optional(Type.String()),
                strStartDate: Type.Optional(Type.String()),
                strMobilePhone: Type.Optional(Type.String()),
                strPayrollId: Type.Optional(Type.String()),
                fltWeekDayRate: Type.Optional(Type.Number()),
                Phone: Type.Optional(Type.String()),
                intAgreementId: Type.Optional(Type.Number()),
                blnSetPrimary: Type.Optional(Type.Boolean()),
                ...queryPaging,
            }, { additionalProperties: false }),
            async execute(params, config, context) {
                return run(operations.employees, params, config, context.signal);
            },
        }),
        tool({
            name: "deputy_timesheets",
            label: "Deputy Timesheets",
            description: "Timesheets: resource QUERY, get details/resource, start/end/pause/approve/discard/update. Convenience QUERY filters map onto search clauses.",
            parameters: Type.Object({
                action: actionSchema(["query", "get", "get_resource", "start", "end", "pause", "approve", "discard", "update"], "Timesheet operation to run. Writes require an explicit action."),
                timesheetId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
                employeeId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
                paycycleId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
                intTimesheetId: Type.Optional(Type.Number()),
                intEmployeeId: Type.Optional(Type.Number()),
                intOpunitId: Type.Optional(Type.Number()),
                intStartTimestamp: Type.Optional(Type.Number()),
                intEndTimestamp: Type.Optional(Type.Number()),
                intRosterId: Type.Optional(Type.Number()),
                strComment: Type.Optional(Type.String()),
                strDate: Type.Optional(Type.String()),
                intMealbreakMinute: Type.Optional(Type.Number()),
                arrSlots: Type.Optional(Type.Unknown()),
                startTimeGt: Type.Optional(Type.Number()),
                startTimeLt: Type.Optional(Type.Number()),
                timeApproved: Type.Optional(Type.Boolean()),
                payRuleApproved: Type.Optional(Type.Boolean()),
                discarded: Type.Optional(Type.Boolean()),
                isInProgress: Type.Optional(Type.Boolean()),
                isLeave: Type.Optional(Type.Boolean()),
                disputed: Type.Optional(Type.Boolean()),
                ...queryPaging,
            }, { additionalProperties: false }),
            async execute(params, config, context) {
                return run(operations.timesheets, params, config, context.signal);
            },
        }),
        tool({
            name: "deputy_leave",
            label: "Deputy Leave",
            description: "Leave: resource QUERY, get by id, supervise create, and GET leave-by-employee.",
            parameters: Type.Object({
                action: actionSchema(["query", "get", "create", "employee"], "Leave operation to run. Writes require an explicit action."),
                leaveId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
                employeeId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
                Status: Type.Optional(Type.Number()),
                Employee: Type.Optional(Type.Number()),
                DateStart: Type.Optional(Type.String()),
                DateEnd: Type.Optional(Type.String()),
                ApprovalComment: Type.Optional(Type.String()),
                ActionOverlappingRosters: Type.Optional(Type.Number()),
                ...queryPaging,
            }, { additionalProperties: false }),
            async execute(params, config, context) {
                return run(operations.leave, params, config, context.signal);
            },
        }),
        tool({
            name: "deputy_rosters",
            label: "Deputy Rosters",
            description: "Rosters: resource QUERY, last-12h/next-36h list, get by id, copy/publish/discard.",
            parameters: Type.Object({
                action: actionSchema(["query", "list", "get", "copy", "publish", "discard"], "Roster operation to run. Writes require an explicit action."),
                rosterId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
                strFromDate: Type.Optional(Type.String()),
                strToDate: Type.Optional(Type.String()),
                intOperationalUnitArray: Type.Optional(Type.Unknown()),
                blnRequireErrorDetails: Type.Optional(Type.Number()),
                intMode: Type.Optional(Type.Number()),
                blnAllLocationsMode: Type.Optional(Type.Number()),
                intRosterArray: Type.Optional(Type.Unknown()),
                ...queryPaging,
            }, { additionalProperties: false }),
            async execute(params, config, context) {
                return run(operations.rosters, params, config, context.signal);
            },
        }),
        tool({
            name: "deputy_locations",
            label: "Deputy Locations",
            description: "Locations (Company): list, get by id, create, update, archive. Hard delete is omitted.",
            parameters: Type.Object({
                action: actionSchema(["list", "get", "create", "update", "archive"], "Location operation to run. Writes require an explicit action."),
                companyId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
                strWorkplaceName: Type.Optional(Type.String()),
                strWorkplaceCode: Type.Optional(Type.String()),
                strAddress: Type.Optional(Type.String()),
                strAddressNotes: Type.Optional(Type.String()),
                intParentCompany: Type.Optional(Type.Number()),
                intIsWorkplace: Type.Optional(Type.Number()),
                intIsPayrollEntity: Type.Optional(Type.Number()),
                strTimezone: Type.Optional(Type.String()),
                strPayrollExportCode: Type.Optional(Type.String()),
                payload: Type.Optional(Type.Unknown()),
            }, { additionalProperties: false }),
            async execute(params, config, context) {
                return run(operations.locations, params, config, context.signal);
            },
        }),
        tool({
            name: "deputy_areas",
            label: "Deputy Areas",
            description: "Operational units (areas): list, QUERY, create department, update, delete.",
            parameters: Type.Object({
                action: actionSchema(["list", "query", "create", "update", "delete"], "Area operation to run. Writes require an explicit action."),
                operationalUnitId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
                intCompanyId: Type.Optional(Type.Number()),
                strOpunitName: Type.Optional(Type.String()),
                strAddress: Type.Optional(Type.String()),
                strExportName: Type.Optional(Type.String()),
                intSortOrder: Type.Optional(Type.Number()),
                intOpunitType: Type.Optional(Type.Number()),
                intAddressId: Type.Optional(Type.Number()),
                arrTrainingId: Type.Optional(Type.Unknown()),
                ...queryPaging,
            }, { additionalProperties: false }),
            async execute(params, config, context) {
                return run(operations.areas, params, config, context.signal);
            },
        }),
        tool({
            name: "deputy_pay",
            label: "Deputy Pay",
            description: "GET-only pay reads: TimesheetPayReturn, EmployeePaycycle, EmployeeAgreement, and PayPeriod QUERY/get. Create/update throw.",
            parameters: Type.Object({
                action: actionSchema([
                    "timesheet_pay_return_query",
                    "employee_paycycle_query",
                    "employee_paycycle_get",
                    "employee_agreement_query",
                    "employee_agreement_get",
                    "pay_period_query",
                    "pay_period_get",
                ], "Pay read operation. Writes are rejected."),
                paycycleId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
                agreementId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
                payPeriodId: Type.Optional(Type.Union([Type.String(), Type.Number()])),
                ...queryPaging,
            }, { additionalProperties: false }),
            async execute(params, config, context) {
                return run(operations.pay, params, config, context.signal);
            },
        }),
    ],
});
