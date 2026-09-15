import { describe, expect, it } from "vitest";
import { mcpServerConfig, resolveOrigin } from "./origin.js";

describe("field origin", () => {
  it("is a credential-free Field public origin", () => {
    expect(resolveOrigin({ origin: "https://field.example.test/" })).toEqual({
      origin: "https://field.example.test",
      mcpUrl: "https://field.example.test/mcp",
      auth: "oauth",
      scopes: "catalog.read catalog.write quote.read quote.draft",
    });
    expect(() => resolveOrigin({})).toThrow(/valid URL/);
    expect(() => resolveOrigin({ origin: "file:///tmp/field" })).toThrow(/http or https/);
    expect(() => resolveOrigin({ origin: "https://user:secret@field.example.test" })).toThrow(/credentials/);
    expect(() => resolveOrigin({ origin: "https://field.example.test/app" })).toThrow(/path/);
  });

  it("builds OAuth streamable HTTP MCP config", () => {
    expect(mcpServerConfig("https://field.example.test")).toEqual({
      url: "https://field.example.test/mcp",
      transport: "streamable-http",
      auth: "oauth",
      oauth: { scope: "catalog.read catalog.write quote.read quote.draft" },
      toolFilter: { include: ["field_*"] },
    });
  });
});
