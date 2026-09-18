import {describe, expect, it, vi} from "vitest";
import {createFergusClient, createRateGovernor} from "./client.js";
import {resolveConfig} from "./config.js";
import {files, invoices, jobs, timeEntries} from "./operations.js";

describe("release behavior", () => {
  it.each([429, 500, 503])("never automatically repeats writes after HTTP %s", async (status) => {
    const fetchImpl = vi.fn(async () => new Response("{}", {status, headers: {"retry-after": "0"}}));
    const client = createFergusClient({
      token: "synthetic",
      fetchImpl: fetchImpl as unknown as typeof fetch,
      governor: createRateGovernor({maxRequestsPerMinute: 80}),
    });
    await expect(client.request("POST", "/jobs", {body: {jobType: "Quote"}})).rejects.toThrow();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("rejects identifier path injection", async () => {
    const request = vi.fn(async () => ({}));
    const config = resolveConfig({apiToken: "synthetic"});
    await expect(jobs({request} as never, config, {action: "get", jobId: "../other"})).rejects.toThrow(
      "Invalid jobId",
    );
  });

  it("refuses form/certificate upload and invoice/time writes", async () => {
    const request = vi.fn(async () => ({}));
    const config = resolveConfig({apiToken: "synthetic"});
    await expect(
      files({request} as never, config, {action: "upload", entityType: "form", entityId: "1", fileBase64: "YQ=="}),
    ).rejects.toThrow("list and download only");
    await expect(invoices({request} as never, config, {action: "create"})).rejects.toThrow("GET-only");
    await expect(timeEntries({request} as never, config, {action: "create"})).rejects.toThrow("GET-only");
  });

  it("has no regional default and validates company/timezone configuration", () => {
    expect(resolveConfig({apiToken: "synthetic"}).timezone).toBeUndefined();
    expect(resolveConfig({apiToken: "synthetic"}).maxRequestsPerMinute).toBe(80);
    expect(() => resolveConfig({apiToken: "synthetic", companyId: "../other"})).toThrow();
    expect(() => resolveConfig({apiToken: "synthetic", timezone: "not-a-zone"})).toThrow();
  });
});
