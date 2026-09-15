---
name: field
description: Connect OpenClaw to a customer's Field instance with OAuth MCP for quotes, costs, prices, markup, and drafts.
---

# Field

Use Field's OAuth-protected MCP tools after the operator has authenticated this OpenClaw against their Field origin. Never use a Field CLI, a workspace runbook skill, `FIELD_TOKEN`, or a copied bearer. Never infer an endpoint, edit Field data files, or construct a parallel quote model.

0. If Field tools are missing, call `field_connection_status` and ask the operator to run the returned `mcp set` / `mcp login` commands. Do not invent a token.
1. Start with the smallest read tool that identifies current state. For catalog work, search then fetch the exact item; for quote work, list then fetch the exact job. Confirm the returned code/UID or job ID before continuing.
2. Use `field_pricing_review` for existing cost/price analysis and `field_markup_preview` for hypothetical markup or margin math. Keep markup and margin distinct: markup divides profit by cost; margin divides profit by sell price.
3. Inspect component children or categories before proposing structure changes. Preserve Field's rule that catalog type classifies the item but does not control whether it may have children.
4. Validate a quote with `field_quote_validate` before proposing a draft update or recalculation. Treat warnings about missing costs or inputs as unresolved review work, not permission to guess.
5. Preview every mutation by omitting `apply` or setting it false. Show the proposed request, before-state, and returned `expectedVersion` to the operator.
6. Apply only after the operator explicitly approves that preview. Pass `apply: true`, confirmation exactly `APPLY`, and the unchanged `expectedVersion`; if the tool reports a stale version, stop and produce a new preview rather than retrying automatically.
7. Report the returned before/after audit and any Field API error. Never claim success from the request alone.

## Hard boundary

This plugin has no tool for sending, emailing, publishing, issuing, accepting, invoicing, or taking payment. Do not substitute another tool when asked to send or publish a quote.

Do not place bearer tokens in prompts, tool arguments, plugin config, logs, or documentation. The user authenticates against their Field instance; OpenClaw stores only its own OAuth credentials.
