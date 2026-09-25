export const LOCAL_HARD_CAP_PER_MINUTE = 120;
export const DEFAULT_LOCAL_LIMIT_PER_MINUTE = 60;
export const QUERY_MAX = 500;
export const QUERY_DEFAULT = 100;
export const INSTALL_HOST_RE = /^[a-z0-9][a-z0-9-]{0,62}\.(au|eu|uk|us|na)\.deputy\.com$/;
export function capRequestsPerMinute(value) {
    if (typeof value !== "number" || !Number.isFinite(value) || value < 1) {
        return DEFAULT_LOCAL_LIMIT_PER_MINUTE;
    }
    return Math.min(Math.trunc(value), LOCAL_HARD_CAP_PER_MINUTE);
}
export function validateInstallHost(value) {
    if (typeof value !== "string") {
        throw new Error("Deputy plugin config is missing installHost.");
    }
    const host = value.trim();
    if (!host)
        throw new Error("Deputy plugin config is missing installHost.");
    if (host !== host.toLowerCase() ||
        host.includes("://") ||
        host.includes("/") ||
        host.includes(":") ||
        host.includes("@") ||
        host.includes("?") ||
        host.includes("#") ||
        host.includes("\\") ||
        host === "once.deputy.com" ||
        host.endsWith(".once.deputy.com")) {
        throw new Error("Invalid Deputy installHost.");
    }
    if (!INSTALL_HOST_RE.test(host)) {
        throw new Error("Invalid Deputy installHost.");
    }
    return host;
}
export function resolveConfig(config) {
    const raw = config?.apiToken;
    if (typeof raw !== "string") {
        throw new Error("Deputy apiToken is an unresolved SecretRef; store it as a SecretRef and let the host resolve it.");
    }
    const token = raw.trim();
    if (!token) {
        throw new Error("Deputy plugin config is missing apiToken. Store the permanent token as a SecretRef.");
    }
    const timezone = config.timezone?.trim() || undefined;
    if (timezone) {
        try {
            new Intl.DateTimeFormat("en", { timeZone: timezone }).format();
        }
        catch {
            throw new Error("Invalid IANA timezone.");
        }
    }
    return {
        token,
        installHost: validateInstallHost(config.installHost),
        maxRequestsPerMinute: capRequestsPerMinute(config.maxRequestsPerMinute),
        timezone,
    };
}
export function capLimit(value, fallback = QUERY_DEFAULT, max = QUERY_MAX) {
    return typeof value === "number" && Number.isFinite(value) && value >= 1
        ? Math.min(Math.trunc(value), max)
        : fallback;
}
export function compact(input) {
    return Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined));
}
