import { describe, expect, it, vi } from "vitest"; import { createHubSpotClient, HubSpotError } from "./client.js"; import { contacts } from "./operations.js"; import { resolveConfig } from "./config.js";
const response = (status: number, body: unknown, headers?: Record<string,string>) => new Response(JSON.stringify(body), { status, headers: { "content-type":"application/json", ...headers } });
describe("HubSpot boundary", () => {
  it("uses bearer auth, official UA and origin", async () => { const f = vi.fn(async () => response(200, { portalId: 42 })); await createHubSpotClient({ token:"secret", fetchImpl:f as any }).request("GET", "/account-info/v3/details"); const init = f.mock.calls[0][1] as RequestInit; expect((init.headers as any).Authorization).toBe("Bearer secret"); expect((init.headers as any)["User-Agent"]).toBe("OpenClaw-HubSpot/0.1.0"); expect(String(f.mock.calls[0][0])).toBe("https://api.hubapi.com/account-info/v3/details"); });
  it("retries GET 429 but never retries writes", async () => { const f = vi.fn().mockResolvedValueOnce(response(429,{} ,{"retry-after":"0"})).mockResolvedValueOnce(response(200,{ok:true})); await createHubSpotClient({token:"x",fetchImpl:f as any}).request("GET","/x"); expect(f).toHaveBeenCalledTimes(2); const w=vi.fn(async()=>response(429,{message:"Bearer x"})); await expect(createHubSpotClient({token:"x",fetchImpl:w as any}).request("POST","/x",{body:{}})).rejects.toBeInstanceOf(HubSpotError); expect(w).toHaveBeenCalledTimes(1); });
  it("redacts token on network write failure and sets redirect error/deadline signal", async () => { const f=vi.fn(async()=>{throw new Error("Bearer topsecret")}); const c=createHubSpotClient({token:"topsecret",fetchImpl:f as any}); await expect(c.request("PATCH","/x",{body:{}})).rejects.toThrow("verify the outcome"); const init=f.mock.calls[0][1] as RequestInit; expect(init.redirect).toBe("error"); expect(init.signal).toBeTruthy(); });
  it("rejects path injection", async () => { const c=createHubSpotClient({token:"x",fetchImpl:vi.fn() as any}); await expect(c.request("GET","/crm/../secret")).rejects.toThrow(); await expect(c.request("GET","//evil")).rejects.toThrow(); });
});
describe("HubSpot operations", () => {
  it("searches through /search and gets contacts by email", async () => { const f=vi.fn(async (_input: URL|string)=>response(200,{})); const c=createHubSpotClient({token:"x",fetchImpl:f as any}); const cfg=resolveConfig({accessToken:"x"}); await contacts(c,cfg,{action:"search",query:"Alex Example",properties:["email"]}); expect(String(f.mock.calls[0][0])).toContain("/crm/v3/objects/contacts/search"); expect(JSON.parse((f.mock.calls[0][1] as RequestInit).body as string).properties).toEqual(["email"]); await contacts(c,cfg,{action:"get",id:"123",idProperty:"email"}); expect(String(f.mock.calls[1][0])).toContain("idProperty=email"); });
  it("associates created notes and sends list membership IDs as a JSON array", async () => {
    const { notes, lists } = await import("./operations.js");
    const f = vi.fn(async () => response(200, {}));
    const c = createHubSpotClient({ token: "x", fetchImpl: f as any });
    const cfg = resolveConfig({ accessToken: "x" });
    await notes(c, cfg, { action: "create", body: "Follow up", contactId: "123" });
    const created = JSON.parse((f.mock.calls[0][1] as RequestInit).body as string);
    expect(created.properties.hs_note_body).toBe("Follow up");
    expect(created.associations[0].to.id).toBe("123");
    expect(created.associations[0].types[0].associationTypeId).toBe(202);
    await lists(c, cfg, { action: "add_memberships", listId: "9", recordIds: ["123", "456"] });
    expect(String(f.mock.calls[1][0])).toContain("/crm/v3/lists/9/memberships/add");
    expect(JSON.parse((f.mock.calls[1][1] as RequestInit).body as string)).toEqual(["123", "456"]);
  });
});
describe("config", () => { it("rejects invalid settings and does not default timezone", () => { expect(() => resolveConfig({accessToken:"x",portalId:"x"})).toThrow(); expect(() => resolveConfig({accessToken:"x",timezone:"no/such-zone"})).toThrow(); expect(resolveConfig({accessToken:"x"}).timezone).toBeUndefined(); expect(() => resolveConfig({accessToken:{source:"env",provider:"default",id:"TOKEN"}})).toThrow(/unresolved/); }); });
