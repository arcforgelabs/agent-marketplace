import { QUERY_DEFAULT, QUERY_MAX, capLimit, compact } from "./config.js";
const PAY_READ = new Set([
    "timesheet_pay_return_query",
    "employee_paycycle_query",
    "employee_paycycle_get",
    "employee_agreement_query",
    "employee_agreement_get",
    "pay_period_query",
    "pay_period_get",
]);
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
function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
function rejectHostPaths(params) {
    if (Object.prototype.hasOwnProperty.call(params, "filePath") || params.filePath !== undefined) {
        throw new Error("Host file paths are not accepted.");
    }
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
function unwrap(record) {
    if (!isPlainObject(record))
        return {};
    return isPlainObject(record.data) ? record.data : record;
}
function publicIdentity(value) {
    const record = unwrap(value);
    const keep = [
        "Id",
        "EmployeeId",
        "Employee",
        "Name",
        "DisplayName",
        "FirstName",
        "LastName",
        "PrimaryEmail",
        "Email",
        "Company",
        "CompanyId",
        "Portfolio",
        "Login",
        "UserId",
    ];
    const out = {};
    for (const key of keep) {
        if (record[key] !== undefined)
            out[key] = record[key];
    }
    return out;
}
function companySummary(value) {
    const list = Array.isArray(value)
        ? value
        : isPlainObject(value) && Array.isArray(value.data)
            ? value.data
            : [];
    const ids = list
        .map((item) => {
        const record = unwrap(item);
        const raw = asString(record.Id) ?? asString(record.id);
        return raw && /^\d+$/.test(raw) ? raw : undefined;
    })
        .filter((item) => Boolean(item));
    return { count: ids.length, ids };
}
function addSearchClause(search, field, data, type) {
    if (data === undefined || data === null || data === "")
        return;
    const key = `s${Object.keys(search).length + 1}`;
    search[key] = { field, data, type };
}
function queryBody(params, extraSearch = {}) {
    const extra = isPlainObject(params.payload) ? { ...params.payload } : {};
    const search = isPlainObject(extra.search) ? { ...extra.search } : {};
    for (const [key, clause] of Object.entries(extraSearch)) {
        search[key] = clause;
    }
    const max = capLimit(params.max ?? extra.max, QUERY_DEFAULT, QUERY_MAX);
    const startRaw = params.start ?? extra.start;
    const start = typeof startRaw === "number" && Number.isFinite(startRaw) && startRaw >= 0
        ? Math.trunc(startRaw)
        : extra.start;
    const sort = params.sort ?? extra.sort;
    const join = params.join ?? extra.join;
    return compact({
        search: Object.keys(search).length ? search : undefined,
        sort,
        start,
        max,
        join,
    });
}
function resourceQuery(client, resource, params, extraSearch = {}) {
    return client.request("POST", `/v1/resource/${resource}/QUERY`, { body: queryBody(params, extraSearch) });
}
export async function status(client, config, params = {}) {
    rejectHostPaths(params);
    const [me, companies] = await Promise.all([
        client.request("GET", "/v1/me"),
        client.request("GET", "/v1/resource/Company"),
    ]);
    const company = companySummary(companies);
    return {
        connected: true,
        installHost: config.installHost,
        me: publicIdentity(me),
        companyCount: company.count,
        companyIds: company.ids,
        timezone: config.timezone ?? null,
        rateLimit: client.governor.snapshot(),
    };
}
export async function employees(client, _config, params) {
    rejectHostPaths(params);
    const action = requiredAction(params, "deputy_employees");
    switch (action) {
        case "list":
            return client.request("GET", "/v1/supervise/employee");
        case "get":
            return client.request("GET", `/v1/supervise/employee/${id(params, "employeeId", action)}`);
        case "create":
            return client.request("POST", "/v1/supervise/employee", {
                body: payloadOf(params, [
                    "strFirstName",
                    "strLastName",
                    "intCompanyId",
                    "intGender",
                    "strCountryCode",
                    "strDob",
                    "strStartDate",
                    "strMobilePhone",
                    "strPayrollId",
                    "fltWeekDayRate",
                ]),
            });
        case "update":
            return client.request("POST", `/v1/supervise/employee/${id(params, "employeeId", action)}`, {
                body: payloadOf(params, ["Phone", "strFirstName", "strLastName", "strMobilePhone"]),
            });
        case "terminate":
            return client.request("POST", `/v1/supervise/employee/${id(params, "employeeId", action)}/terminate`);
        case "reactivate":
            return client.request("POST", `/v1/supervise/employee/${id(params, "employeeId", action)}/activate`);
        case "invite":
            return client.request("POST", `/v1/supervise/employee/${id(params, "employeeId", action)}/invite`);
        case "add_location":
            return client.request("POST", `/v1/supervise/employee/${id(params, "employeeId", action)}/assoc/${id(params, "companyId", action)}`, { body: payloadOf(params, ["intAgreementId", "blnSetPrimary"]) });
        case "remove_location":
            return client.request("POST", `/v1/supervise/employee/${id(params, "employeeId", action)}/unassoc/${id(params, "companyId", action)}`);
        case "query":
            return resourceQuery(client, "Employee", params);
        case "delete":
        case "delete_account":
            throw new Error("Employee account deletion is omitted; use terminate.");
        default:
            throw new Error(`Unknown action for deputy_employees: ${action}.`);
    }
}
function timesheetSearch(params) {
    const search = {};
    const employeeId = optionalId(params, "employeeId");
    if (employeeId)
        addSearchClause(search, "Employee", Number(employeeId), "eq");
    if (params.startTimeGt !== undefined)
        addSearchClause(search, "StartTime", params.startTimeGt, "gt");
    if (params.startTimeLt !== undefined)
        addSearchClause(search, "StartTime", params.startTimeLt, "lt");
    if (params.timeApproved !== undefined)
        addSearchClause(search, "TimeApproved", params.timeApproved, "eq");
    if (params.payRuleApproved !== undefined)
        addSearchClause(search, "PayRuleApproved", params.payRuleApproved, "eq");
    if (params.discarded !== undefined)
        addSearchClause(search, "Discarded", params.discarded, "eq");
    if (params.isInProgress !== undefined)
        addSearchClause(search, "IsInProgress", params.isInProgress, "eq");
    if (params.isLeave !== undefined)
        addSearchClause(search, "IsLeave", params.isLeave, "eq");
    if (params.disputed !== undefined)
        addSearchClause(search, "Disputed", params.disputed, "eq");
    const paycycleId = optionalId(params, "paycycleId");
    if (paycycleId)
        addSearchClause(search, "PaycycleId", Number(paycycleId), "eq");
    return search;
}
export async function timesheets(client, _config, params) {
    rejectHostPaths(params);
    const action = requiredAction(params, "deputy_timesheets");
    const timesheetFields = [
        "intTimesheetId",
        "intEmployeeId",
        "intOpunitId",
        "IntOpunitId",
        "intStartTimestamp",
        "intEndTimestamp",
        "intRosterId",
        "strComment",
        "strDate",
        "intStartTimeHour",
        "intStartTimeMinute",
        "intEndTimeHour",
        "intEndTimeMinute",
        "intMealbreakMinute",
        "arrSlots",
        "blnIsInprogress",
        "blnApproveTimesheet",
    ];
    switch (action) {
        case "query":
            return resourceQuery(client, "Timesheet", params, timesheetSearch(params));
        case "get":
            return client.request("GET", `/v1/supervise/timesheet/${id(params, "timesheetId", action)}/details`);
        case "get_resource":
            return client.request("GET", `/v1/resource/Timesheet/${id(params, "timesheetId", action)}`);
        case "start":
            return client.request("POST", "/v1/supervise/timesheet/start", { body: payloadOf(params, timesheetFields) });
        case "end":
            return client.request("POST", "/v1/supervise/timesheet/end", { body: payloadOf(params, timesheetFields) });
        case "pause":
            return client.request("POST", "/v1/supervise/timesheet/pause", { body: payloadOf(params, timesheetFields) });
        case "approve":
            return client.request("POST", "/v1/supervise/timesheet/approve", { body: payloadOf(params, timesheetFields) });
        case "discard":
            return client.request("POST", "/v1/supervise/timesheet/discard", { body: payloadOf(params, timesheetFields) });
        case "update":
            return client.request("POST", "/v1/supervise/timesheet/update", { body: payloadOf(params, timesheetFields) });
        default:
            throw new Error(`Unknown action for deputy_timesheets: ${action}.`);
    }
}
export async function leave(client, _config, params) {
    rejectHostPaths(params);
    const action = requiredAction(params, "deputy_leave");
    switch (action) {
        case "query":
            return resourceQuery(client, "Leave", params);
        case "get":
            return client.request("GET", `/v1/resource/Leave/${id(params, "leaveId", action)}`);
        case "create":
            return client.request("POST", "/v1/supervise/leave", {
                body: payloadOf(params, [
                    "Status",
                    "Employee",
                    "DateStart",
                    "DateEnd",
                    "ApprovalComment",
                    "ActionOverlappingRosters",
                ]),
            });
        case "employee":
            return client.request("GET", `/v1/supervise/leave/${id(params, "employeeId", action)}`);
        default:
            throw new Error(`Unknown action for deputy_leave: ${action}.`);
    }
}
export async function rosters(client, _config, params) {
    rejectHostPaths(params);
    const action = requiredAction(params, "deputy_rosters");
    switch (action) {
        case "query":
            return resourceQuery(client, "Roster", params);
        case "list":
            return client.request("GET", "/v1/supervise/roster");
        case "get":
            return client.request("GET", `/v1/resource/Roster/${id(params, "rosterId", action)}`);
        case "copy":
            return client.request("POST", "/v1/supervise/roster/copy", {
                body: payloadOf(params, ["strFromDate", "strToDate", "intOperationalUnitArray", "blnRequireErrorDetails"]),
            });
        case "publish":
            return client.request("POST", "/v1/supervise/roster/publish", {
                body: payloadOf(params, ["intMode", "blnAllLocationsMode", "intRosterArray"]),
            });
        case "discard":
            return client.request("POST", "/v1/supervise/roster/discard", {
                body: payloadOf(params, ["intRosterArray"]),
            });
        default:
            throw new Error(`Unknown action for deputy_rosters: ${action}.`);
    }
}
export async function locations(client, _config, params) {
    rejectHostPaths(params);
    const action = requiredAction(params, "deputy_locations");
    const fields = [
        "strWorkplaceName",
        "strWorkplaceCode",
        "strAddress",
        "strAddressNotes",
        "intParentCompany",
        "intIsWorkplace",
        "intIsPayrollEntity",
        "strTimezone",
        "strPayrollExportCode",
    ];
    switch (action) {
        case "list":
            return client.request("GET", "/v1/resource/Company");
        case "get":
            return client.request("GET", `/v1/my/location/${id(params, "companyId", action)}`);
        case "create":
            return client.request("PUT", "/v1/supervise/company", { body: payloadOf(params, fields) });
        case "update":
            return client.request("POST", `/v1/supervise/company/${id(params, "companyId", action)}`, {
                body: payloadOf(params, fields),
            });
        case "archive":
            return client.request("POST", `/v1/supervise/company/${id(params, "companyId", action)}/archive`);
        case "delete":
            throw new Error("Location delete is omitted; use archive.");
        default:
            throw new Error(`Unknown action for deputy_locations: ${action}.`);
    }
}
export async function areas(client, _config, params) {
    rejectHostPaths(params);
    const action = requiredAction(params, "deputy_areas");
    switch (action) {
        case "list":
            return client.request("GET", "/v1/resource/OperationalUnit");
        case "query":
            return resourceQuery(client, "OperationalUnit", params);
        case "create":
            return client.request("PUT", "/v1/supervise/department", {
                body: payloadOf(params, [
                    "intCompanyId",
                    "strOpunitName",
                    "strAddress",
                    "strExportName",
                    "intSortOrder",
                    "intOpunitType",
                ]),
            });
        case "update":
            return client.request("POST", `/v1/resource/OperationalUnit/${id(params, "operationalUnitId", action)}`, {
                body: payloadOf(params, ["intCompanyId", "intAddressId", "strOpunitName", "strExportName", "arrTrainingId"]),
            });
        case "delete":
            return client.request("DELETE", `/v1/resource/OperationalUnit/${id(params, "operationalUnitId", action)}`);
        default:
            throw new Error(`Unknown action for deputy_areas: ${action}.`);
    }
}
export async function pay(client, _config, params) {
    rejectHostPaths(params);
    const action = requiredAction(params, "deputy_pay");
    if (action === "create" || action === "update" || !PAY_READ.has(action)) {
        throw new Error("deputy_pay is GET-only; pay rule and agreement writes are not implemented.");
    }
    switch (action) {
        case "timesheet_pay_return_query":
            return resourceQuery(client, "TimesheetPayReturn", params);
        case "employee_paycycle_query":
            return resourceQuery(client, "EmployeePaycycle", params);
        case "employee_paycycle_get":
            return client.request("GET", `/v1/resource/EmployeePaycycle/${id(params, "paycycleId", action)}`);
        case "employee_agreement_query":
            return resourceQuery(client, "EmployeeAgreement", params);
        case "employee_agreement_get":
            return client.request("GET", `/v1/resource/EmployeeAgreement/${id(params, "agreementId", action)}`);
        case "pay_period_query":
            return resourceQuery(client, "PayPeriod", params);
        case "pay_period_get":
            return client.request("GET", `/v1/resource/PayPeriod/${id(params, "payPeriodId", action)}`);
        default:
            throw new Error("deputy_pay is GET-only; pay rule and agreement writes are not implemented.");
    }
}
