# API and Browser Access

## API Reality

Zavy release notes may mention a Zavy 360 API, but support has clarified that
API access is not open or self-service. Access goes through the Partner API
Program and requires business verification, approved use case, partner
certification, scopes, and Zavy-defined security/data-handling rules.

Use support/partner documentation as the source of truth for any official API
work. Do not rely on internal app GraphQL as a supported integration surface.

## Internal GraphQL: Read Carefully, Mutate Conservatively

The authenticated web app uses GraphQL and Apollo cache. This is useful for:

- Reading exact current state when the UI is ambiguous.
- Discovering IDs for UI-visible objects.
- Verifying whether a UI save actually persisted.
- Understanding how patient-facing booking pages expose settings.

It is risky for mutation because some inputs are not patch-like. In particular,
`updateAppointmentReason` can clear omitted arrays such as practitioner
assignments. Before any mutation:

1. Read the existing full record.
2. Build the update payload by copying fields to preserve.
3. Change only the intended fields.
4. Verify affected fields after save.

For appointment reason updates, preserve at least:

- `name`
- `description`
- `minutes`
- `colour`
- `state`
- `visible`
- `patientVisibility`
- `integrations`
- `categoryId`
- `practitionerIds`
- `shiftTypeIds`
- `catalogueItems`
- template IDs: reminder, confirmation, created, updated, review
- `requireDeposit`
- `depositAmount`
- `showTotalCost`
- `showDepositCost`
- `prepaymentType`

## CDP Inspection Pattern

Use the existing authenticated tab:

```bash
curl -s http://127.0.0.1:9226/json/list | jq -r '.[] | [.id,.title,.url] | @tsv' | rg 'zavy|bookings'
```

### Connecting the WebSocket (gotchas)

- The DevTools WS handshake is rejected with **403 Forbidden** unless you
  suppress the Origin header. With Python `websocket-client`:
  `create_connection(url, suppress_origin=True)`. (Alternatively launch the
  browser with `--remote-allow-origins=*`.)
- `websocket-client` may need `pip install websocket-client --break-system-packages`
  on a PEP-668 system.
- **Tab IDs are session-scoped.** A stale/closed tab gives
  `500 No such target id`; re-list with `/json/list` and reconnect. The user may
  close your tab mid-task.
- Create your **own** tab so you don't disturb the user's:
  `curl -s -X PUT "http://127.0.0.1:9226/json/new?<url>"`. Read-only evals against
  the user's active tab are fine; navigation/mutation should happen in your tab.
- `Page.captureScreenshot` works on background tabs — use it to verify rendered
  UI (e.g. rich-text formatting) without focusing the tab.

Then evaluate JavaScript over the target WebSocket. Useful snippets:

```js
// Apollo cache summary
window.__APOLLO_CLIENT__?.cache?.extract?.()
```

```js
// Visible controls in a modal
(() => {
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const root = [...document.querySelectorAll('.zavy-modal,[role=dialog],.ant-modal')].filter(visible)[0] || document.body;
  return [...root.querySelectorAll('input,textarea,button,[role=button]')]
    .map((el, i) => ({
      i,
      tag: el.tagName,
      type: el.type || '',
      name: el.name || '',
      text: (el.innerText || el.getAttribute('aria-label') || el.title || '').trim(),
      value: 'value' in el ? el.value : '',
      visible: visible(el)
    }));
})()
```

## Public Booking Verification

Always check patient-facing behavior through the public booking page after
online booking changes. Admin state can look correct while public filters,
patient-type visibility, practitioner availability, or service names differ.

Verification should cover:

- Location selection if multiple locations exist.
- New/existing patient paths if visibility differs.
- Filter chips/categories.
- Service names and descriptions.
- Practitioner list and bookable times.
