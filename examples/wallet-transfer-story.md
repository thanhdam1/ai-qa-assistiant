# Sample story: Wallet-to-wallet transfers

## Module context

This sample exercises requirement analysis, OpenAPI contract review, and test case generation for
money movement. It is intentionally complex and is paired with `wallet-transfer.openapi.yaml`.

## User story

As a verified wallet customer, I want to quote and submit a transfer between wallets so that I can
move money while seeing the fee and outcome before I confirm.

## Acceptance criteria

1. A customer can request a transfer quote by selecting a source wallet, a destination wallet, and
   an amount. The quote returns the amount, fee, total debit, currency, and expiration time.
2. The source and destination wallets must be different, belong to the authenticated customer, and
   use the same currency.
3. The transfer amount is an integer number of minor currency units. For VND, the allowed amount is
   from 10,000 through 50,000,000 inclusive per transfer.
4. The customer can submit a transfer only with an unexpired quote and a valid one-time password
   (OTP). The quote's amount and wallets cannot be changed during submission.
5. The source wallet is debited by amount plus quoted fee; the destination wallet is credited by
   exactly the transfer amount.
6. A transfer is rejected if the source wallet does not have enough available balance for amount
   plus fee. Neither wallet balance changes when a transfer is rejected.
7. The total amount debited from one customer across all outgoing transfers must not exceed
   100,000,000 VND per business day, inclusive of the transfer that reaches the limit.
8. If simultaneous transfers would make the same source wallet's available balance negative, at
   most the transfers that fit the available balance may succeed. A rejected transfer must not
   debit either wallet.
9. Submitting the same confirmed request again with the same `Idempotency-Key` must not create an
   additional transfer or debit the source wallet again.
10. A customer can view their own transfer details and list their wallet's transfers by status,
    using pagination.
11. A customer may cancel a transfer only while its status is `pending`. A completed transfer cannot
    be cancelled through this flow.

## Business context

- Wallet balances and transfer amounts are represented as integer minor currency units; no floating
  point arithmetic is allowed.
- The quote expires exactly 2 minutes after it is created. A quote at its expiration instant is
  expired.
- An OTP has a 5-minute validity period. The story does not specify the number of allowed failed
  attempts or the lockout behavior.
- A successful transfer changes both wallet balances as one business operation: both changes occur
  or neither occurs.
- The daily outgoing limit is 100,000,000 VND. The story does not define the timezone or reset
  boundary for a business day.
- The idempotency requirement applies to resubmission of the same confirmed request, but key scope,
  retention period, and behavior when a key is reused with a different body are unspecified.
- The supported currency list is not defined. The numeric limits above apply only to VND.

## Dependencies

- Authentication identifies the customer and their verified status.
- OTP verification is required, but its provider, delivery channel, and integration boundary are
  unspecified.
- A quote supplies the transfer fee and total debit. The fee calculation and fee schedule are not
  defined by this story.
- No external bank, payment gateway, queue, or ledger architecture is confirmed. Do not invent one.

## Deliberate review points

- The OpenAPI schema allows any positive integer amount; the story adds a VND-specific minimum and
  maximum that the contract does not express.
- The OpenAPI contract declares `409` for an expired quote or idempotency conflict but does not
  define the error response body or distinguish those conflict reasons.
- The story defines exact quote and OTP expiry boundaries; the OpenAPI contract only uses date-time
  fields and does not describe expiry semantics.
- The story limits daily debits in VND but does not define business-day timezone or reset time.
- Reusing an idempotency key with a different request body is unspecified.
- The OpenAPI cancellation operation describes pending-only cancellation, while the story also
  states completed transfers cannot be cancelled; terminal statuses beyond `completed` are not
  defined.
- Failed OTP attempt limits and account lockout behavior are unknown.
- OTP delivery is a dependency, but its implementation and integration boundary are not specified.

## Suggested test focus

Exercise amount boundaries, source/destination ownership and currency checks, quote and OTP expiry
boundaries, fee-inclusive balance checks, daily limit boundaries, concurrent source-wallet debits,
idempotent retries, pending versus completed cancellation, authorization on transfer history, and
pagination. Mark behaviors without a confirmed rule as `needs_clarification`. Do not assume an OTP
provider, payment rail, ledger service, or lockout policy.
