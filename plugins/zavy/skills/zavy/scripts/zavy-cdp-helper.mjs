#!/usr/bin/env node
import zlib from "node:zlib";

const DEFAULT_CDP = process.env.ZAVY_CDP || "http://127.0.0.1:9226";
// No hardcoded practice: supply --base-url or set ZAVY_BASE_URL (e.g. https://yourpractice.zavy.com).
const DEFAULT_BASE_URL = process.env.ZAVY_BASE_URL || "";
const NON_CLINICAL_NOTE_TYPES = ["general", "internal", "follow_up", "comment"];
const STAFF_ROLES = [
  "receptionist",
  "practitioner",
  "practice_manager",
  "owner",
  "admin",
  "assistant",
  "back_office",
  "administrator",
  "support",
];
const PATIENT_STATES = ["active", "inactive", "blocked", "pending"];

const HELP = `Usage:
  zavy-cdp-helper.mjs list-tabs [options]
  zavy-cdp-helper.mjs schema [options] [--type <GraphQLType>]
  zavy-cdp-helper.mjs search-patient --name <name> [--dob YYYY-MM-DD] [--phone <phone>] [options]
  zavy-cdp-helper.mjs search-staff --name <name> [options]
  zavy-cdp-helper.mjs notes --patient-guid <guid> [options]

Options:
  --cdp <url>             Chrome/Brave CDP endpoint (or set ZAVY_CDP). Default: ${DEFAULT_CDP}
  --base-url <url>        Zavy practice origin, e.g. https://yourpractice.zavy.com
                          (or set ZAVY_BASE_URL). Required — no default.
  --name <text>           Search text for patient/staff lookup.
  --dob YYYY-MM-DD        Prefer a patient match with this date of birth.
  --phone <phone>         Prefer a patient match with this phone/mobile.
  --patient-guid <guid>   UserPracticeLink.guid for a patient.
  --author-id <id>        Filter notes by Zavy user-practice-link author ID.
  --created-start <iso>   Filter notes by createdAt start.
  --created-end <iso>     Filter notes by createdAt end.
  --first <n>             Page size. Default: 20.
  --include-clinical      Include clinical note types. Default: non-clinical only.
  --raw-content           Keep encoded note content as returned by Zavy.
  --pretty                Pretty-print JSON.

Safety:
  This helper attaches to the user's existing authenticated Zavy browser
  session and performs read-only GraphQL queries from inside that browser
  context. It prints results to stdout and does not write files. Output can
  contain patient data; keep it local and do not commit it.`;

function parseArgs(argv) {
  const args = {
    command: argv[2],
    cdp: DEFAULT_CDP,
    baseUrl: DEFAULT_BASE_URL,
    first: 20,
    includeClinical: false,
    rawContent: false,
    pretty: false,
  };

  if (args.command === "--help" || args.command === "-h") {
    args.help = true;
    args.command = null;
    return args;
  }

  for (let i = 3; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--help" || arg === "-h") {
      args.help = true;
    } else if (arg === "--cdp") {
      args.cdp = argv[++i];
    } else if (arg === "--base-url") {
      args.baseUrl = argv[++i];
    } else if (arg === "--name") {
      args.name = argv[++i];
    } else if (arg === "--dob") {
      args.dob = argv[++i];
    } else if (arg === "--phone") {
      args.phone = argv[++i];
    } else if (arg === "--patient-guid") {
      args.patientGuid = argv[++i];
    } else if (arg === "--author-id") {
      args.authorId = argv[++i];
    } else if (arg === "--created-start") {
      args.createdStart = argv[++i];
    } else if (arg === "--created-end") {
      args.createdEnd = argv[++i];
    } else if (arg === "--type") {
      args.type = argv[++i];
    } else if (arg === "--first") {
      args.first = Number(argv[++i]);
    } else if (arg === "--include-clinical") {
      args.includeClinical = true;
    } else if (arg === "--raw-content") {
      args.rawContent = true;
    } else if (arg === "--pretty") {
      args.pretty = true;
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }

  return args;
}

async function getJson(url, init) {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw new Error(`${init?.method || "GET"} ${url} failed with ${response.status}`);
  }
  return response.json();
}

async function listTargets(cdp) {
  return getJson(`${cdp.replace(/\/$/, "")}/json/list`);
}

async function findZavyTarget(cdp, baseUrl) {
  const targets = await listTargets(cdp);
  const target = targets.find((entry) => (entry.url || "").startsWith(baseUrl));
  if (!target?.webSocketDebuggerUrl) {
    throw new Error(
      `No authenticated Zavy tab found for ${baseUrl}. Open Zavy in the browser exposed at ${cdp}.`
    );
  }
  return target;
}

class CdpClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.nextId = 1;
    this.pending = new Map();
  }

  async connect() {
    if (typeof WebSocket !== "function") {
      throw new Error("This helper requires a Node.js runtime with global WebSocket support.");
    }
    this.ws = new WebSocket(this.wsUrl);
    await new Promise((resolve, reject) => {
      this.ws.addEventListener("open", resolve, { once: true });
      this.ws.addEventListener("error", reject, { once: true });
    });
    this.ws.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (!message.id || !this.pending.has(message.id)) return;
      const pending = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(`${pending.method}: ${message.error.message}`));
      else pending.resolve(message.result);
    });
  }

  send(method, params = {}) {
    const id = this.nextId;
    this.nextId += 1;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject, method });
    });
  }

  close() {
    this.ws?.close();
  }
}

async function evaluate(client, expression) {
  const result = await client.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  }
  return result.result.value;
}

async function runInZavy(args, callback) {
  if (!args.baseUrl) {
    throw new Error(
      "Missing Zavy practice origin. Pass --base-url https://yourpractice.zavy.com or set ZAVY_BASE_URL."
    );
  }
  const target = await findZavyTarget(args.cdp, args.baseUrl);
  const client = new CdpClient(target.webSocketDebuggerUrl);
  await client.connect();
  try {
    await client.send("Runtime.enable");
    return await callback(client);
  } finally {
    client.close();
  }
}

async function gql(client, query, variables = {}, operationName = null) {
  const expression = `(async () => {
    const response = await fetch("/graphql", {
      method: "POST",
      credentials: "include",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        operationName: ${JSON.stringify(operationName)},
        query: ${JSON.stringify(query)},
        variables: ${JSON.stringify(variables)}
      })
    });
    return await response.json();
  })()`;
  const json = await evaluate(client, expression);
  if (json?.errors?.length) {
    throw new Error(JSON.stringify(json.errors, null, 2));
  }
  return json.data;
}

function stripPhone(value) {
  return String(value || "")
    .replace(/\D/g, "")
    .replace(/^61/, "0");
}

function compactProfile(profile = {}) {
  return {
    fullName: profile.fullName || null,
    fullNameWithTitle: profile.fullNameWithTitle || null,
    preferredFullName: profile.preferredFullName || null,
    dateOfBirth: profile.dateOfBirth || null,
    email: profile.email || null,
    internationalMobile: profile.internationalMobile || null,
  };
}

function decodeBase64Brotli(value) {
  if (!value) return "";
  const raw = value.startsWith("encoded:") ? value.slice("encoded:".length) : value;
  const html = zlib.brotliDecompressSync(Buffer.from(raw, "base64")).toString("utf8");
  return htmlToText(html);
}

function htmlToText(html) {
  return String(html || "")
    .replace(/<br\s*\/?\s*>/gi, "\n")
    .replace(/<\/p>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&amp;/g, "&")
    .replace(/&nbsp;/g, " ")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+\n/g, "\n")
    .replace(/\n\s+/g, "\n")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

async function searchUpc(client, attributes, first) {
  const query = `query SearchUpc($attributes: UpcSearchInput, $first: Int) {
    upc(attributes: $attributes, first: $first) {
      totalCount
      edges {
        node {
          id
          guid
          state
          role { name slug }
          profile {
            fullName
            fullNameWithTitle
            preferredFullName
            dateOfBirth
            email
            internationalMobile
          }
        }
      }
    }
  }`;
  const data = await gql(client, query, { attributes, first }, "SearchUpc");
  return {
    totalCount: data.upc.totalCount,
    records: data.upc.edges.map((edge) => ({
      id: edge.node.id,
      guid: edge.node.guid,
      state: edge.node.state,
      role: edge.node.role,
      profile: compactProfile(edge.node.profile),
    })),
  };
}

function choosePatient(records, args) {
  if (!records.length) return null;
  return (
    records.find(
      (record) =>
        (!args.dob || record.profile.dateOfBirth === args.dob) &&
        (!args.phone || stripPhone(record.profile.internationalMobile) === stripPhone(args.phone))
    ) ||
    records.find((record) => !args.dob || record.profile.dateOfBirth === args.dob) ||
    records[0]
  );
}

async function fetchNotes(client, args) {
  const query = `query Notes($attributes: NotesSearchParameters, $first: Int) {
    notes(attributes: $attributes, first: $first) {
      totalCount
      pageInfo { hasNextPage endCursor }
      edges {
        node {
          id
          guid
          createdAt
          updatedAt
          state
          sticky
          autoNote
          content
          noteType { type name }
          author { id profile { fullName fullNameWithTitle email } }
          updatedBy { id profile { fullName fullNameWithTitle email } }
        }
      }
    }
  }`;
  const attributes = { patients: [args.patientGuid] };
  if (!args.includeClinical) attributes.noteTypes = NON_CLINICAL_NOTE_TYPES;
  if (args.authorId) attributes.authors = [args.authorId];
  if (args.createdStart || args.createdEnd) {
    attributes.createdAtTime = {
      ...(args.createdStart ? { start: args.createdStart } : {}),
      ...(args.createdEnd ? { end: args.createdEnd } : {}),
    };
  }
  const data = await gql(client, query, { attributes, first: args.first }, "Notes");
  return {
    totalCount: data.notes.totalCount,
    pageInfo: data.notes.pageInfo,
    notes: data.notes.edges.map((edge) => {
      const note = edge.node;
      return {
        id: note.id,
        guid: note.guid,
        createdAt: note.createdAt,
        updatedAt: note.updatedAt,
        state: note.state,
        sticky: note.sticky,
        autoNote: note.autoNote,
        noteType: note.noteType,
        author: note.author
          ? { id: note.author.id, profile: compactProfile(note.author.profile) }
          : null,
        updatedBy: note.updatedBy
          ? { id: note.updatedBy.id, profile: compactProfile(note.updatedBy.profile) }
          : null,
        content: args.rawContent ? note.content : decodeBase64Brotli(note.content),
      };
    }),
  };
}

async function schema(client, typeName) {
  if (typeName) {
    const query = `query SchemaType($name: String!) {
      __type(name: $name) {
        kind
        name
        inputFields { name type { kind name ofType { kind name ofType { kind name } } } }
        fields { name type { kind name ofType { kind name ofType { kind name } } } args { name type { kind name ofType { kind name } } } }
        enumValues { name }
      }
    }`;
    return gql(client, query, { name: typeName }, "SchemaType");
  }
  const query = `query SchemaSummary {
    __schema {
      queryType {
        fields {
          name
          args { name type { kind name ofType { kind name ofType { kind name } } } }
          type { kind name ofType { kind name } }
        }
      }
    }
  }`;
  const data = await gql(client, query, {}, "SchemaSummary");
  return {
    queryFields: data.__schema.queryType.fields.filter((field) =>
      /upc|userPractice|note|recall|treatment/i.test(field.name)
    ),
  };
}

function print(value, pretty) {
  console.log(JSON.stringify(value, null, pretty ? 2 : 0));
}

async function main() {
  const args = parseArgs(process.argv);
  if (!args.command || args.help) {
    console.log(HELP);
    return;
  }

  if (args.command === "list-tabs") {
    const tabs = (await listTargets(args.cdp))
      .filter((target) => /zavy|bookings/i.test(`${target.title || ""} ${target.url || ""}`))
      .map((target) => ({
        id: target.id,
        type: target.type,
        title: target.title,
        url: target.url,
      }));
    print(tabs, args.pretty);
    return;
  }

  const result = await runInZavy(args, async (client) => {
    if (args.command === "schema") return schema(client, args.type);

    if (args.command === "search-patient") {
      if (!args.name) throw new Error("search-patient requires --name.");
      const result = await searchUpc(
        client,
        { search: args.name, roles: ["patient", "lead"], state: PATIENT_STATES },
        args.first
      );
      return { ...result, bestMatch: choosePatient(result.records, args) };
    }

    if (args.command === "search-staff") {
      if (!args.name) throw new Error("search-staff requires --name.");
      return searchUpc(
        client,
        { search: args.name, roles: STAFF_ROLES, state: PATIENT_STATES },
        args.first
      );
    }

    if (args.command === "notes") {
      if (!args.patientGuid) throw new Error("notes requires --patient-guid.");
      return fetchNotes(client, args);
    }

    throw new Error(`Unknown command: ${args.command}`);
  });

  print(result, args.pretty);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
