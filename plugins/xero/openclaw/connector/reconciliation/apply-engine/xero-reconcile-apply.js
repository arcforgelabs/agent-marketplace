#!/usr/bin/env node
"use strict";

/*
 * Xero BankRec Playwright apply engine.
 *
 * Python owns capture/report orchestration. This file owns the live browser
 * mechanics that Python/CDP string snippets handled poorly: Xero's classic
 * BankRec panel mixes custom legacy completers and ExtJS combos. A selection is
 * only committed when the rendered option is clicked and the backing hidden
 * field receives an id/code. Setting visible input values is not enough.
 */

const fs = require("fs");
const path = require("path");
const http = require("http");
const https = require("https");

// Playwright's CDP transport can emit late rejections while Xero re-renders the
// BankRec list after an OK click (session-iframe churn). Node's default policy
// kills the process before the result JSON is printed, making a successful
// apply look like a failure. Record to stderr and continue; main() owns error
// reporting on stdout.
process.on("unhandledRejection", (reason) => {
  console.error("unhandledRejection:", (reason && reason.message) || String(reason));
});
process.on("uncaughtException", (error) => {
  console.error("uncaughtException:", (error && error.message) || String(error));
});

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    const item = argv[i];
    if (!item.startsWith("--")) continue;
    const key = item.slice(2).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    if (key === "apply" || key === "stdin" || key === "applyBatch") {
      args[key] = true;
      continue;
    }
    args[key] = argv[i + 1];
    i += 1;
  }
  return args;
}

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function lower(value) {
  return normalizeText(value).toLowerCase();
}

function moneyText(amount) {
  const n = Number(amount);
  return Number.isFinite(n) ? Math.abs(n).toFixed(2) : "";
}

function hashFromStatementLineId(statementLineId) {
  return String(statementLineId || "").replace(/-/g, "");
}

function loadInput(args) {
  if (!args.stdin) return {};
  const raw = fs.readFileSync(0, "utf8").trim();
  return raw ? JSON.parse(raw) : {};
}

function loadPlan(args, input) {
  let payload;
  if (input && (Array.isArray(input.lines) || Array.isArray(input.plan) || Array.isArray(input))) {
    payload = input;
  } else if (args.planJson) {
    payload = JSON.parse(args.planJson);
  } else if (args.plan) {
    payload = JSON.parse(fs.readFileSync(args.plan, "utf8"));
  } else {
    throw new Error("Pass --plan-json or --plan.");
  }
  const rows = Array.isArray(payload) ? payload : payload.lines || payload.plan;
  if (!Array.isArray(rows)) throw new Error("Plan must be an array or object with lines/plan.");
  return rows;
}

function loadPlaywright() {
  const candidates = [
    process.env.PLAYWRIGHT_MODULE,
    "playwright",
    path.join(process.env.HOME || "", "repos", "openclaw", "node_modules", "playwright"),
  ].filter(Boolean);
  for (const candidate of candidates) {
    try {
      return require(candidate);
    } catch {
      // Try the next known local install location.
    }
  }
  throw new Error("Node Playwright is required. Install it locally or set PLAYWRIGHT_MODULE to require.resolve('playwright').");
}

async function detachBrowser(browser) {
  const connection = browser && browser._connection;
  if (connection && typeof connection.close === "function") {
    connection.close();
  }
}

function choiceQuery(choice) {
  if (!choice) return "";
  if (typeof choice === "string") return choice;
  return choice.query || choice.code || choice.display || choice.name || choice.id || "";
}

function choiceDisplay(choice) {
  if (!choice) return "";
  if (typeof choice === "string") return choice;
  return choice.display || choice.name || choice.label || choice.query || choice.code || "";
}

function choiceId(choice) {
  if (!choice || typeof choice === "string") return "";
  return choice.id || choice.xero_id || choice.account_id || choice.tax_id || "";
}

async function findBankRecPage(browser, targetId, cdpEndpoint) {
  const pages = [];
  for (const context of browser.contexts()) {
    pages.push(...context.pages());
  }
  if (targetId) {
    const targetUrl = await targetUrlFromId(cdpEndpoint, targetId).catch((error) => {
      throw new Error(`Requested target id ${targetId} could not be resolved: ${error.message || String(error)}`);
    });
    const byUrl = pages.find((page) => page.url().split("#")[0] === targetUrl.split("#")[0]);
    if (byUrl) return byUrl;
    throw new Error(`Requested target id ${targetId} is not attached to an open browser page.`);
  }
  const reconcilePages = [];
  for (const page of pages) {
    const haystack = `${page.url()} ${await page.title().catch(() => "")}`.toLowerCase();
    if (/(bankrec\.aspx|\/bank\/reconcile|reconcile|reconciliation|cash coding|bank account)/i.test(haystack)) {
      reconcilePages.push(page);
    }
  }
  if (reconcilePages.length > 0) return reconcilePages[0];
  const xero = pages.find((page) => /xero\.com/i.test(page.url()));
  if (xero) return xero;
  throw new Error("No open Xero BankRec page found in the supplied browser session.");
}

function cdpHttpBase(endpoint) {
  const parsed = new URL(endpoint);
  const scheme = parsed.protocol === "wss:" ? "https:" : parsed.protocol === "ws:" ? "http:" : parsed.protocol;
  return `${scheme}//${parsed.host}`;
}

function redactUrl(value) {
  try {
    const parsed = new URL(value);
    return `${parsed.origin}${parsed.pathname}`;
  } catch {
    return String(value || "").split("?")[0].split("#")[0];
  }
}

function fetchJson(url) {
  const client = url.startsWith("https:") ? https : http;
  return new Promise((resolve, reject) => {
    const req = client.get(url, { timeout: 5000 }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => { body += chunk; });
      res.on("end", () => {
        try {
          resolve(JSON.parse(body));
        } catch (error) {
          reject(error);
        }
      });
    });
    req.on("error", reject);
    req.on("timeout", () => {
      req.destroy(new Error(`Timed out fetching ${url}`));
    });
  });
}

async function targetUrlFromId(endpoint, targetId) {
  if (!endpoint || !targetId) return "";
  const targets = await fetchJson(`${cdpHttpBase(endpoint)}/json/list`);
  if (!Array.isArray(targets)) return "";
  const target = targets.find((item) => item && String(item.id || "") === String(targetId));
  return target ? String(target.url || "") : "";
}

async function visibleInnerText(locator, timeoutMs = 500) {
  try {
    return normalizeText(await locator.innerText({ timeout: timeoutMs }));
  } catch {
    return "";
  }
}

async function resolveRow(page, line) {
  const h = hashFromStatementLineId(line.statement_line_id);
  const selectors = [
    `#sl${h}`,
    `[data-statementlineid="${line.statement_line_id}"]`,
  ];
  for (const selector of selectors) {
    const locator = page.locator(selector);
    const count = await locator.count();
    if (count === 1) {
      const row = locator.first();
      const text = await visibleInnerText(row);
      const expectedAmount = moneyText(line.amount);
      if (expectedAmount && !text.replace(/,/g, "").includes(expectedAmount)) {
        throw new Error(`Row amount guard failed for ${line.statement_line_id}: expected ${expectedAmount}.`);
      }
      return { row, hash: h, text };
    }
    if (count > 1) throw new Error(`Row guard failed: ${count} rows matched ${selector}.`);
  }
  throw new Error(`Statement row not found: ${line.statement_line_id}`);
}

async function maybeClick(row, selector, label) {
  const loc = row.locator(selector).first();
  if ((await loc.count()) < 1) throw new Error(`${label} not found: ${selector}`);
  await loc.click();
}

async function readHiddenValue(page, hiddenId) {
  return page.evaluate((id) => {
    const el = document.getElementById(id);
    return el ? String(el.value || el.getAttribute("value") || "") : "";
  }, hiddenId);
}

async function findFloatingOption(page, expectedText) {
  const expected = lower(expectedText);
  // Fast path: explicit autocomplete option rows. The contact completer renders
  // visible `.search-item` rows (matched letter wrapped in a child <b>), and ExtJS
  // combos render `.x-combo-list-item`. Match these directly by visible innerText,
  // bypassing the generic child-skip heuristic below (which wrongly skips a row
  // whose matched substring lives in a child element).
  // The autocompleter renders matches asynchronously (debounced query), so poll for
  // the option row to appear rather than checking once.
  const optionSelector = ".x-combo-list .search-item, .x-layer .search-item, .search-item, .x-combo-list-item, .x-boundlist-item";
  // Event-driven head start: wait for the floating layer to render its first
  // visible option row instead of burning fixed poll cycles while Xero's
  // debounced server-side search is still in flight. Errors fall through to
  // the poll loop — some layers render options hidden-then-shown and miss the
  // visibility event entirely.
  try {
    await page.locator(optionSelector).first().waitFor({ state: "visible", timeout: 6000 });
  } catch {
    // Poll loop below still gets its chance.
  }
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const optionRows = page.locator(optionSelector);
    const orCount = Math.min(await optionRows.count(), 300);
    const orExact = [];
    const orPartial = [];
    for (let i = 0; i < orCount; i += 1) {
      const cand = optionRows.nth(i);
      let box;
      try { box = await cand.boundingBox({ timeout: 80 }); } catch { box = null; }
      if (!box || box.width <= 0 || box.height <= 0) continue;
      const text = lower(await visibleInnerText(cand, 120));
      if (!text) continue;
      if (text === expected) orExact.push(cand);
      else if (text.includes(expected) || expected.includes(text)) orPartial.push(cand);
    }
    if (orExact.length >= 1) return orExact[0];
    if (orPartial.length === 1) return orPartial[0];
    await page.waitForTimeout(350);
  }
  // Generic fallback. Scan floating-layer descendants first (the option list
  // always lives in one); only if that yields nothing, pay for the body-wide
  // scan — the original 2000-element sweep is the multi-second hot spot.
  const scanScopes = [
    { locator: page.locator(".x-layer, .x-combo-list, .x-boundlist, [class*='completer']").locator("div, li, td, a"), cap: 600 },
    { locator: page.locator(".x-combo-list-item, body div, body li, body td, body a"), cap: 2000 },
  ];
  const matches = [];
  for (const scope of scanScopes) {
  const candidates = scope.locator;
  const count = Math.min(await candidates.count().catch(() => 0), scope.cap);
  for (let i = 0; i < count; i += 1) {
    const candidate = candidates.nth(i);
    let box;
    try {
      box = await candidate.boundingBox({ timeout: 100 });
    } catch {
      box = null;
    }
    if (!box || box.width <= 0 || box.height <= 0) continue;
    const text = lower(await visibleInnerText(candidate, 120));
    if (!text) continue;
    const hasMatchingChild = await candidate.evaluate((el, expectedValue) => {
      for (const child of Array.from(el.children || [])) {
        const childText = String(child.innerText || child.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
        if (childText && (childText === expectedValue || childText.includes(expectedValue))) return true;
      }
      return false;
    }, expected).catch(() => false);
    if (hasMatchingChild) continue;
    if (text === expected || text.includes(expected) || expected.includes(text)) {
      const isExtOption = await candidate.evaluate((el) => el.classList.contains("x-combo-list-item")).catch(() => false);
      matches.push({ candidate, text, isExtOption });
    }
  }
  if (matches.length > 0) break;
  }
  if (matches.length === 1) return matches[0].candidate;
  if (matches.length > 1) {
    const extExact = matches.filter((m) => m.isExtOption && m.text === expected);
    if (extExact.length === 1) return extExact[0].candidate;
    const exact = matches.filter((m) => m.text === expected);
    if (exact.length === 1) return exact[0].candidate;
    matches.sort((a, b) => {
      if (a.isExtOption !== b.isExtOption) return a.isExtOption ? -1 : 1;
      return a.text.length - b.text.length;
    });
    if (matches[0] && matches[1] && matches[0].text !== matches[1].text && matches[0].text.length < matches[1].text.length) {
      return matches[0].candidate;
    }
    throw new Error(`Autocomplete option ambiguous for ${expectedText}: ${matches.slice(0, 5).map((m) => m.text).join(" | ")}`);
  }
  throw new Error(`Autocomplete option not found for ${expectedText}`);
}

async function commitCompleter(page, row, spec) {
  const visible = row.locator(spec.visibleSelector).first();
  if ((await visible.count()) < 1) throw new Error(`${spec.label} visible input not found: ${spec.visibleSelector}`);
  const query = choiceQuery(spec.choice);
  const display = choiceDisplay(spec.choice) || query;
  const expectedId = choiceId(spec.choice);
  if (!expectedId) {
    throw new Error(`${spec.label} selection must include an expected hidden id/code before it can be committed.`);
  }
  const existingHiddenValue = await readHiddenValue(page, spec.hiddenId);
  const existingVisibleValue = normalizeText(await visible.inputValue().catch(() => ""));
  if (existingHiddenValue === expectedId) {
    return { label: spec.label, hidden_id: spec.hiddenId, hidden_value: existingHiddenValue, visible_value: existingVisibleValue };
  }
  await visible.click();
  await visible.fill("");
  // Optional plan field: type a fuller search string (e.g. "881 - Owner A")
  // so Xero's server-side search returns exactly one row on the first render.
  // Defaults to the query; matching below still verifies against display/id.
  const typeText = (spec.choice && typeof spec.choice === "object" && spec.choice.type_text)
    ? String(spec.choice.type_text)
    : query;
  await visible.type(typeText, { delay: 35 });
  const option = await findFloatingOption(page, display || query);
  await option.click();
  await page.waitForTimeout(250);
  const hiddenValue = await readHiddenValue(page, spec.hiddenId);
  if (!hiddenValue) throw new Error(`${spec.label} did not commit hidden field ${spec.hiddenId}.`);
  if (hiddenValue !== expectedId) {
    throw new Error(`${spec.label} committed unexpected id/code for ${spec.hiddenId}: expected ${expectedId}, got ${hiddenValue}`);
  }
  const visibleValue = normalizeText(await visible.inputValue().catch(() => ""));
  return { label: spec.label, hidden_id: spec.hiddenId, hidden_value: hiddenValue, visible_value: visibleValue };
}

async function fillText(row, selector, value) {
  if (!value) return null;
  const loc = row.locator(selector).first();
  if ((await loc.count()) < 1) throw new Error(`Requested text field not found: ${selector}`);
  await loc.fill(String(value));
  const actual = await loc.inputValue().catch(() => "");
  if (actual !== String(value)) throw new Error(`Requested text field did not retain value: ${selector}`);
  return { selector, value: String(value) };
}

async function okReady(page, row, hash, action) {
  const checks = [];
  if (action === "create") {
    checks.push(["paidAccount", `paidAccount${hash}`]);
  } else if (action === "transfer") {
    checks.push(["transferAccount", `transferAccount${hash}`]);
  }
  const values = {};
  for (const [label, id] of checks) {
    const value = await page.evaluate((fieldId) => {
      const el = document.getElementById(fieldId);
      return el ? String(el.value || el.getAttribute("value") || "") : "";
    }, id);
    if (!value) throw new Error(`OK guard failed: ${label} hidden field ${id} is empty.`);
    values[id] = value;
  }
  const ok = row.locator("a.okayButton").first();
  if ((await ok.count()) < 1) throw new Error("OK guard failed: row-scoped a.okayButton not found.");
  return { hidden_values: values, ok_present: true };
}

async function isCandidateSelected(locator) {
  return locator.evaluate((el) => {
    const checkbox = el.querySelector('input[type="checkbox"], input[type="radio"]');
    if (checkbox && checkbox.checked) return true;
    const aria = el.getAttribute("aria-selected") || el.getAttribute("aria-checked");
    if (aria === "true") return true;
    const classText = String(el.className || "").toLowerCase();
    return /\b(selected|checked|active|matched)\b/.test(classText);
  }).catch(() => false);
}

async function clickMatchSelector(candidate) {
  const control = candidate.locator('input[type="checkbox"], input[type="radio"], [role="checkbox"], [aria-label*="select" i], button:has-text("Select"), button:has-text("Add"), a:has-text("Select"), a:has-text("Add")').first();
  if ((await control.count()) > 0) {
    await control.click();
    return "control";
  }
  await candidate.click();
  return "candidate";
}

async function selectMatchTarget(page, row, line) {
  const target = normalizeText(line.match_text || line.transaction_text || line.expected_match || line.reference);
  if (!target) throw new Error("Match guard failed: plan must include match_text/transaction_text/expected_match or reference.");
  const expected = lower(target);
  const amount = moneyText(line.match_amount || line.expected_match_amount || line.amount);
  const rowText = await visibleInnerText(row);

  // Xero auto-selects a suggested match when an exact-amount posted transaction
  // exists, rendering a `div.statement.matched` strip in the row. If that strip
  // already shows the expected counterparty and amount, the selection is done —
  // clicking it again would toggle it off. Verify and return.
  const matchedStrip = row.locator("div.statement.matched").first();
  if ((await matchedStrip.count()) > 0) {
    const stripText = await visibleInnerText(matchedStrip);
    if (lower(stripText).includes(expected) && (!amount || stripText.replace(/,/g, "").includes(amount))) {
      return {
        match_text: target,
        amount,
        verified: true,
        selected_before: true,
        selected_after: true,
        selection_method: "pre-matched-suggestion",
        candidate_text_excerpt: stripText.slice(0, 240),
      };
    }
  }
  const candidates = row.locator("tr, li, td, div, a, label");
  const count = Math.min(await candidates.count(), 1000);
  const matches = [];

  for (let i = 0; i < count; i += 1) {
    const candidate = candidates.nth(i);
    let box;
    try {
      box = await candidate.boundingBox({ timeout: 100 });
    } catch {
      box = null;
    }
    if (!box || box.width <= 0 || box.height <= 0) continue;
    const text = await visibleInnerText(candidate);
    const normalized = lower(text);
    if (!normalized || !normalized.includes(expected)) continue;
    if (amount && !text.replace(/,/g, "").includes(amount)) continue;
    const isWholeRow = text === rowText;
    const isChrome = await candidate.evaluate((el) => Boolean(
      el.querySelector("a.t1, a.t2, a.t3, a.okayButton") ||
      el.closest("a.t1, a.t2, a.t3, a.okayButton")
    )).catch(() => false);
    if (isWholeRow || isChrome) continue;
    const selected = await isCandidateSelected(candidate);
    const hasSelector = await candidate.locator('input[type="checkbox"], input[type="radio"], [role="checkbox"], [aria-label*="select" i], button:has-text("Select"), button:has-text("Add"), a:has-text("Select"), a:has-text("Add")').count() > 0;
    matches.push({ candidate, text, selected, hasSelector });
  }

  if (matches.length === 0) {
    throw new Error(`Match guard failed: no selectable transaction candidate shows ${target}.`);
  }
  matches.sort((a, b) => {
    if (a.selected !== b.selected) return a.selected ? -1 : 1;
    if (a.hasSelector !== b.hasSelector) return a.hasSelector ? -1 : 1;
    return a.text.length - b.text.length;
  });
  if (matches.length > 1 && matches[0].text === matches[1].text && matches[0].selected === matches[1].selected && matches[0].hasSelector === matches[1].hasSelector) {
    // Identical-text candidates are usually one row's nested wrappers (tr > td >
    // div). Only treat them as ambiguous when two of them are NOT in a DOM
    // containment chain — i.e. genuinely distinct rows with the same text.
    const sameText = matches.filter((m) => m.text === matches[0].text);
    let nestedChain = true;
    for (let i = 0; i < sameText.length && nestedChain; i += 1) {
      for (let j = i + 1; j < sameText.length && nestedChain; j += 1) {
        const otherHandle = await sameText[j].candidate.elementHandle().catch(() => null);
        if (!otherHandle) { nestedChain = false; break; }
        const related = await sameText[i].candidate.evaluate(
          (el, other) => Boolean(other) && (el.contains(other) || other.contains(el)),
          otherHandle
        ).catch(() => false);
        if (!related) nestedChain = false;
      }
    }
    if (!nestedChain) {
      throw new Error(`Match guard failed: ambiguous transaction candidates for ${target}.`);
    }
  }

  const selectedBefore = matches[0].selected;
  const clicked = selectedBefore ? "already-selected" : await clickMatchSelector(matches[0].candidate);
  await page.waitForTimeout(250);
  let selectedAfter = await isCandidateSelected(matches[0].candidate);
  if (!selectedBefore && !selectedAfter) {
    // Selecting a candidate re-renders the match panel into a selected-match
    // strip, detaching the clicked element (so the class/checkbox probe above
    // reads stale state). Accept row-level evidence instead: the row text
    // changed and the row-scoped OK button is now present.
    const rowTextAfter = await visibleInnerText(row);
    const okPresent = (await row.locator("a.okayButton").count()) > 0;
    if (okPresent && rowTextAfter !== rowText) selectedAfter = true;
  }
  if (!selectedBefore && !selectedAfter) {
    throw new Error(`Match guard failed: transaction candidate for ${target} did not become selected.`);
  }
  return {
    match_text: target,
    amount,
    verified: true,
    selected_before: selectedBefore,
    selected_after: selectedAfter,
    selection_method: clicked,
    candidate_text_excerpt: matches[0].text.slice(0, 240),
  };
}

async function processLine(page, line, apply) {
  const { row, hash, text } = await resolveRow(page, line);
  const action = lower(line.action);
  const result = {
    index: line.index,
    statement_line_id: line.statement_line_id,
    action,
    row_text_excerpt: text.slice(0, 240),
    committed_fields: [],
    text_fields: [],
    applied: false,
  };

  if (action === "create") {
    await maybeClick(row, "a.t2", "Create tab");
    if (line.contact) {
      result.committed_fields.push(await commitCompleter(page, row, {
        label: "contact",
        choice: line.contact,
        visibleSelector: `input#paidTo${hash}_value`,
        hiddenId: `paidToID${hash}`,
      }));
    }
    result.committed_fields.push(await commitCompleter(page, row, {
      label: "account",
      choice: line.account,
      visibleSelector: `input#paidAccount${hash}_value`,
      hiddenId: `paidAccount${hash}`,
    }));
    if (line.tax) {
      result.committed_fields.push(await commitCompleter(page, row, {
        label: "tax",
        choice: line.tax,
        visibleSelector: `input#paidGSTCode${hash}_value`,
        hiddenId: `paidGSTCode${hash}`,
      }));
    }
    const desc = await fillText(row, `input#paidDesc${hash}`, line.description);
    if (desc) result.text_fields.push(desc);
    const ref = await fillText(row, `input#reference${hash}_value`, line.reference);
    if (ref) result.text_fields.push(ref);
  } else if (action === "transfer") {
    await maybeClick(row, "a.t3", "Transfer tab");
    result.committed_fields.push(await commitCompleter(page, row, {
      label: "transfer_account",
      choice: line.transfer_account,
      visibleSelector: `input#transferAccount${hash}_value`,
      hiddenId: `transferAccount${hash}`,
    }));
  } else if (action === "match") {
    await maybeClick(row, "a.t1", "Match tab");
    result.match_guard = await selectMatchTarget(page, row, line);
  } else {
    throw new Error(`Unsupported action: ${action}`);
  }

  result.guard = await okReady(page, row, hash, action);
  if (apply) {
    await row.locator("a.okayButton").first().click();
    // Reconciliation removes the row asynchronously; the UI update can take several
    // seconds. Poll for detachment rather than asserting after a fixed short wait
    // (a too-short wait yields a false "still present" failure on a successful apply).
    try {
      await page.locator(`#sl${hash}`).first().waitFor({ state: "detached", timeout: 20000 });
    } catch {
      const stillThere = await page.locator(`#sl${hash}`).count();
      if (stillThere > 0) throw new Error(`Apply verification failed: row still present 20s after OK for ${line.statement_line_id}.`);
    }
    result.applied = true;
  }
  return result;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const input = loadInput(args);
  const cdpEndpoint = input.cdp_endpoint || input.cdpEndpoint || args.cdpEndpoint;
  if (!cdpEndpoint) throw new Error("Pass --cdp-endpoint or stdin cdp_endpoint.");
  const timeout = Number(args.timeout || 30) * 1000;
  const plan = loadPlan(args, input);
  const batchLimit = Math.max(1, Number(args.maxApplyLines || 25));
  if (args.apply && plan.length !== 1 && !args.applyBatch) {
    throw new Error("Confirmed apply is limited to exactly one reconciliation line per invocation (pass --apply-batch for a reviewed multi-line plan).");
  }
  if (args.apply && plan.length > batchLimit) {
    throw new Error(`Batch apply refused: plan has ${plan.length} lines, limit ${batchLimit} (override with --max-apply-lines).`);
  }
  // Self-watchdog: the unhandledRejection handler keeps the process alive
  // through late CDP failures, which converts crashes into potential hangs
  // (an awaited promise that never resolves). Always emit a JSON verdict and
  // exit before the Python wrapper's process kill, slightly under its
  // max(timeout+60, timeout*lines*6+30)s budget.
  const watchdogSeconds = Math.max(Number(args.timeout || 30) + 50, Number(args.timeout || 30) * 6 * plan.length + 15);
  const watchdog = setTimeout(() => {
    console.log(JSON.stringify({
      ok: false,
      error: `Engine watchdog deadline reached after ${watchdogSeconds}s — applies may have landed; verify with \`xero-reconcile verify\`.`,
    }, null, 2));
    process.exit(3);
  }, watchdogSeconds * 1000);
  watchdog.unref();

  const { chromium } = loadPlaywright();
  const browser = await chromium.connectOverCDP(cdpEndpoint, { timeout });
  try {
    const page = await findBankRecPage(browser, args.targetId, cdpEndpoint);
    page.setDefaultTimeout(timeout);
    const results = [];
    for (const line of plan) {
      try {
        results.push(await processLine(page, line, Boolean(args.apply)));
      } catch (error) {
        // One bad line must not abandon the rest of a reviewed batch; surface
        // it per-line and let the summary/ok flag report the failure.
        results.push({
          index: line.index,
          statement_line_id: line.statement_line_id,
          action: lower(line.action),
          applied: false,
          error: (error && error.message) || String(error),
        });
      }
    }
    const failed = results.filter((item) => item.error);
    const summary = {
      line_count: plan.length,
      applied_count: results.filter((item) => item.applied).length,
      verified_count: results.filter((item) => item.guard && item.guard.ok_present).length,
      dry_run: !args.apply,
    };
    console.log(JSON.stringify({
      ok: failed.length === 0,
      mode: args.apply ? "apply" : "dry-run",
      page_url: redactUrl(page.url()),
      summary,
      results,
    }, null, 2));
  } finally {
    await detachBrowser(browser);
  }
}

main().catch((error) => {
  console.log(JSON.stringify({ ok: false, error: error.message || String(error) }, null, 2));
  process.exit(1);
});
