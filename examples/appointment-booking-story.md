# Sample story: Clinic appointment booking

## Module context

This story covers the patient and clinic-staff appointment workflow. It is intentionally more
complex than the task sample and is paired with `appointment-booking.openapi.yaml` for testing the
Requirement Review Agent, API Contract Agent, and Test Case Generation Agent together.

## User story

As a patient, I want to find an available clinic appointment, book it, view it, reschedule it, or
cancel it so that I can manage my care. As clinic staff, I want to view appointments for my clinic
so that I can prepare for the day.

## Acceptance criteria

1. An authenticated patient can search availability for a clinic and date range, optionally
   filtering by provider and service. The result includes each slot's start and end time, provider,
   and service.
2. Search requests must cover a range of no more than 90 calendar days. A reversed range is invalid.
3. A patient can book an available slot by submitting its clinic, provider, service, and start time.
   The patient identity comes from the authenticated session and cannot be overridden in the body.
4. A booking is confirmed only when the requested slot is still available when the booking is
   committed. If two patients try to book the same slot concurrently, at most one booking succeeds.
5. A patient can view only their own appointments. Clinic staff can view appointments belonging to
   clinics they are authorized to access.
6. A patient can reschedule their own appointment to another available slot. If the new slot cannot
   be booked, the original appointment remains unchanged.
7. A patient can cancel their own appointment at least 24 hours before its start time. Clinic staff
   can cancel an appointment at any time for an operational reason.
8. Appointment timestamps are exchanged as ISO 8601 values with an explicit UTC offset. The
   displayed appointment time uses the clinic's configured time zone.
9. After a booking is confirmed, the patient receives a confirmation notification. A notification
   failure must not silently turn a confirmed appointment into a failed booking.
10. Clinic staff can list appointments for a clinic by status, with pagination.

## Business context

- A slot is specific to one clinic, provider, service, start time, and end time.
- A slot must not be double-booked, including when booking requests arrive concurrently.
- The application supports patient and clinic-staff roles. Staff access is restricted to authorized
  clinics.
- The maximum search range is 90 calendar days, including the start and end dates.
- Cancellation is allowed exactly 24 hours before the appointment. The story does not define the
  time-zone basis for this comparison.
- Notification delivery is a dependency, but its provider, protocol, retry policy, and delivery-time
  guarantee are not specified.

## Dependencies

- Authentication supplies the current patient or staff identity.
- A source of appointment availability exists, but its ownership and integration boundary are not
  specified.
- A notification capability exists, but its architecture and failure-reporting contract are not
  specified.

## Deliberate review points

- The story says the 90-day range is inclusive, while the OpenAPI schema only gives `from` and `to`
  date-time fields and no maximum range constraint.
- The story says cancellation is permitted at exactly 24 hours, but does not say whether the cutoff
  uses UTC, clinic local time, or the timestamp offset supplied by the client.
- The OpenAPI document declares `409` for slot conflicts but does not define the conflict response
  body.
- The story requires a notification after booking, but the OpenAPI contract does not expose a
  notification operation or define an integration boundary. Do not invent one.
- The contract accepts an `Idempotency-Key` header but does not define key scope, retention, or
  replay behavior.
- The story does not define how daylight-saving transitions affect displayed appointment times.
- Rescheduling must preserve the original booking on failure, but the contract does not specify
  whether rescheduling is atomic or how a failed replacement request is represented.

## Suggested test focus

Check role and clinic authorization, availability filtering, inclusive date-range boundaries,
concurrent booking of one slot, rescheduling rollback, cancellation at and around the 24-hour cutoff,
explicit UTC offsets, pagination, idempotency clarification, and the unconfirmed notification
integration. Do not assume a notification vendor or API exists.
