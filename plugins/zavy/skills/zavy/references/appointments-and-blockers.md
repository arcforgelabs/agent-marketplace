# Appointments, Availability, and Blockers

## Roster vs Calendar Events

Rostered sessions define when a practitioner is generally available for
booking. Appointment/private events occupy specific calendar time inside or
outside those sessions.

Use roster/session changes when changing the underlying recurring availability.
Use private appointments when blocking specific times without changing the
roster.

## Private Appointments as Blockers

Private appointments can block online bookings because they occupy practitioner
calendar time. They are useful for:

- Notes/admin time after appointments.
- One-off unavailability.
- Temporary experiments before changing rosters.

Tradeoffs:

- They block all services, not just one appointment type.
- They can reduce flexible booking options.
- They must be maintained or repeated if used as a multi-week pattern.

For note buffers, a common pattern is a 15-minute private appointment after each
possible booking start/duration window. Example: if 45-minute bookings start on
the hour, block `:45-:00` to prevent back-to-back bookings.

## Deleting or Cancelling Private Appointments

UI pattern:

1. Click the private appointment block.
2. Open `Edit Appt` / full detail.
3. Use delete/cancel/trash from the detail view.

The `X` in small popovers usually only closes the popover.

API/app behavior observed: remove operations may not remove the appointment from
active calendar views; updating state to cancelled may be the effective path.
Verify by querying or refreshing the calendar.

## Blocking for Online Booking Duration Limits

If an appointment type duration is shared across practitioners, changing the
duration may affect everyone. Alternatives:

- Create a practitioner-specific service/shortcut if the UI can hide/filter it
  clearly.
- Use session restrictions for practitioner/service availability.
- Use private blockers to reserve notes time.

Avoid exposing duplicate services that look identical except duration; that is
confusing for patients.

## Verification

For availability changes:

- Check the practitioner calendar day/week view.
- Check public booking slots.
- Check both new and existing patient paths if visibility differs.
- Verify blockers remain after reload and do not accidentally block unrelated
  practitioners.
