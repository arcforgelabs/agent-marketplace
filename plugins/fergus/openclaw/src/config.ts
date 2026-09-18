export type SecretRef = {source: string; provider: string; id: string};

export type FergusPluginConfig = {
  apiToken?: string | SecretRef;
  companyId?: string;
  maxRequestsPerMinute?: number;
  timezone?: string;
};

export type ResolvedFergusConfig = {
  token: string;
  companyId?: string;
  maxRequestsPerMinute: number;
  timezone?: string;
};

export const VENDOR_LIMIT_PER_MINUTE = 100;
export const DEFAULT_LOCAL_LIMIT_PER_MINUTE = 80;

export function capRequestsPerMinute(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 1) {
    return DEFAULT_LOCAL_LIMIT_PER_MINUTE;
  }
  return Math.min(Math.trunc(value), VENDOR_LIMIT_PER_MINUTE);
}

export function resolveConfig(config: FergusPluginConfig): ResolvedFergusConfig {
  const raw = config?.apiToken;
  if (typeof raw !== "string") {
    throw new Error(
      "Fergus apiToken is an unresolved SecretRef; store it as a SecretRef and let the host resolve it.",
    );
  }
  const token = raw.trim();
  if (!token) {
    throw new Error("Fergus plugin config is missing apiToken. Store the company PAT as a SecretRef.");
  }
  const companyId = config.companyId?.trim() || undefined;
  if (companyId && !/^[A-Za-z0-9_-]+$/.test(companyId)) {
    throw new Error("Invalid Fergus companyId.");
  }
  const timezone = config.timezone?.trim() || undefined;
  if (timezone) {
    try {
      new Intl.DateTimeFormat("en", {timeZone: timezone}).format();
    } catch {
      throw new Error("Invalid IANA timezone.");
    }
  }
  return {
    token,
    companyId,
    maxRequestsPerMinute: capRequestsPerMinute(config.maxRequestsPerMinute),
    timezone,
  };
}

export function capLimit(value: unknown, fallback = 10, max = 100): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 1
    ? Math.min(Math.trunc(value), max)
    : fallback;
}

export function compact(input: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined));
}
