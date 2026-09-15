export type SecretRef = { source: string; provider: string; id: string };
export type HubSpotPluginConfig = { accessToken?: string | SecretRef; portalId?: string; timezone?: string };
export type ResolvedHubSpotConfig = { token: string; portalId?: string; timezone?: string };

export function resolveConfig(config: HubSpotPluginConfig): ResolvedHubSpotConfig {
  const raw = config?.accessToken;
  if (typeof raw !== "string") throw new Error("HubSpot accessToken is an unresolved SecretRef; store it as a SecretRef and let the host resolve it.");
  const token = raw.trim();
  if (!token) throw new Error("HubSpot plugin config is missing accessToken. Store the private app token as a SecretRef.");
  const portalId = config.portalId?.trim() || undefined;
  if (portalId && !/^\d+$/.test(portalId)) throw new Error("Invalid HubSpot portalId; it must contain digits only.");
  const timezone = config.timezone?.trim() || undefined;
  if (timezone) { try { new Intl.DateTimeFormat("en", { timeZone: timezone }).format(); } catch { throw new Error("Invalid IANA timezone."); } }
  return { token, portalId, timezone };
}
export function capLimit(value: unknown, fallback = 20, max = 100): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 1 ? Math.min(Math.trunc(value), max) : fallback;
}
export function compact(input: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined));
}
