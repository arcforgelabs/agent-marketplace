---
name: field
description: Connect OpenClaw to a customer's Field instance with OAuth MCP for quotes, costs, prices, markup, and drafts.
---

# Field

Use Field's OAuth-protected MCP tools after the operator has authenticated this OpenClaw against their Field origin. Never use a Field CLI, a workspace runbook skill, `FIELD_TOKEN`, or a copied bearer. Never infer an endpoint, edit Field data files, or construct a parallel quote model.

0. If Field tools are missing, call `field_connection_status` and ask the operator to run the returned `mcp set` / `mcp login` commands. Do not invent a token.
1. Start with the smallest read tool that identifies current state. For catalog work, search then fetch the exact item; for quote work, list then fetch the exact job. Confirm the returned code/UID or job ID before continuing.
2. Use `field_pricing_review` for existing cost/price analysis and `field_markup_preview` for hypothetical math. `field_markup_preview` requires `cost`, `basis` (`markup` or `margin`), and `percent`. Markup divides profit by cost; margin divides profit by sell price and must stay below 100. Do not send both markup and margin percents.
3. Inspect categories with `field_catalog_structure` (no code) or component children with `code`. Preserve Field's rule that catalog type classifies the item but does not control whether it may have children. Use `field_quote_catalog_list` to identify quote catalogs.
4. Read quotes with `field_quote_list` then `field_quote_get`. Default `view` is `quote` (focused). Use `summary` for identity/totals and `full` only when evidence or activity is required. Validate with `field_quote_validate` before proposing a draft update or recalculation. Treat warnings about missing costs or inputs as unresolved review work, not permission to guess.
5. Preview every mutation by omitting `apply` or setting it false. Show the proposed request, before-state, and returned `expectedVersion` to the operator.
6. Apply only after the operator explicitly approves that preview. Pass `apply: true`, confirmation exactly `APPLY`, and the unchanged `expectedVersion`; if the tool reports a stale version, stop and produce a new preview rather than retrying automatically.
7. Report the returned before/after audit and any Field API error. Never claim success from the request alone.

## Live MCP tools

After OAuth login, Field MCP exposes:

- Catalog reads: `field_price_item_list` (`{ items }`), `field_price_item_get`, `field_quote_catalog_list` (`{ catalogs }`), `field_pricing_review`, `field_catalog_structure`
- Catalog writes: `field_price_item_update`, `field_catalog_structure_update`
- Quote reads: `field_quote_list` (`{ quotes }`), `field_quote_get`, `field_quote_validate`
- Quote drafts: `field_quote_draft_create`, `field_quote_draft_update`, `field_quote_recalculate`
- Local calculation: `field_markup_preview`

List tools return records, never top-level arrays.

## Hard boundary

This plugin has no tool for sending, emailing, publishing, issuing, accepting, invoicing, or taking payment. Do not substitute another tool when asked to send or publish a quote.

Do not place bearer tokens in prompts, tool arguments, plugin config, logs, or documentation. The user authenticates against their Field instance; OpenClaw stores only its own OAuth credentials.
