export type GhlPluginConfig = {
  locationId?: string;
  privateIntegrationToken?: string | {source: string; provider: string; id: string};
  timezone?: string;
};

export type ResolvedGhlConfig = {
  locationId: string;
  token: string;
  timezone?: string;
};

export function resolveConfig(config: GhlPluginConfig): ResolvedGhlConfig {
  const locationId = config.locationId?.trim() ?? "";
  const token = typeof config.privateIntegrationToken === "string" ? config.privateIntegrationToken.trim() : "";
  if (!locationId) {
    throw new Error("GoHighLevel plugin config is missing locationId.");
  }
  if (!/^[A-Za-z0-9_-]+$/.test(locationId)) throw new Error("Invalid locationId.");
  if (config.timezone) {
    try { new Intl.DateTimeFormat("en", { timeZone: config.timezone }).format(); }
    catch { throw new Error("Invalid IANA timezone."); }
  }
  if (!token) {
    throw new Error(
      "GoHighLevel plugin config is missing privateIntegrationToken. Store the sub-account PIT as a SecretRef.",
    );
  }
  return {
    locationId,
    token,
    timezone: config.timezone?.trim() || undefined,
  };
}

export function capLimit(limit: number | undefined, fallback = 20, max = 100): number {
  const value = limit ?? fallback;
  if (!Number.isFinite(value) || value < 1) return fallback;
  return Math.min(Math.trunc(value), max);
}

export function compact<T extends Record<string, unknown>>(input: T): Record<string, unknown> {
  const output: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(input)) {
    if (value === undefined) continue;
    output[key] = value;
  }
  return output;
}
