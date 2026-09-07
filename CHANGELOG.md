# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-09-07

First public release.

### Added

- **Bulk listings** — `listings template`, `listings pull`, `listings push`. Create or
  update listings from a CSV, with image upload. New listings are always created as
  drafts; nothing is published automatically.
- **Offline validation** — `listings push --dry-run` and `orders ship --dry-run` check
  every row locally with no API key and no network: title length, the 13-tag ceiling,
  20-character tag limit, Etsy's tag character set, enum values, required fields, and
  whether each referenced image file exists.
- **Orders** — `orders pull` exports receipts to CSV; `orders ship` uploads tracking
  numbers in bulk with carrier validation; `orders carriers` lists valid carrier names
  for a shipping origin.
- **SEO** — `seo audit` scores your listings against Etsy's limits and search
  mechanics; `seo keywords` reports the tags, title phrases and price band of listings
  that actually rank for a term; `seo suggest` combines both for one listing.
- **Setup and diagnostics** — `init` writes a `.env` with hidden input for the shared
  secret and verifies the credential against Etsy; `doctor` checks configuration and
  connectivity; `shop profiles` and `shop taxonomy` resolve the IDs a listing CSV needs.
- **Auth** — OAuth 2.0 with PKCE, automatic token refresh, and least-privilege scopes.
  There is deliberately no delete scope.

### Notes on Etsy's API

These cost real time to establish and are recorded in the code so nobody has to
re-derive them:

- `x-api-key` must carry **both** the keystring and the shared secret, colon-joined, on
  every request including unauthenticated ones. PKCE removes the client secret from the
  *token exchange* only — not from this header.
- Callback URLs may be `http://` or `https://`, and the host must be a **domain name**.
  `localhost` is accepted; `127.0.0.1` is rejected. Etsy's prose docs say https-only,
  which is narrower than what is enforced and leads you to build the wrong flow.
- Rate limits are **per app**. A Personal Access app gets 5 requests/second and 5,000
  per day — not the 10/sec and 10,000/day the general documentation quotes.
- Array form fields such as `tags` and `materials` are **comma-joined strings**, not
  repeated keys. Repeated keys silently drop all but one value.
- `createDraftListing` takes form encoding; `createReceiptShipment` takes JSON.
- There is no idempotency key, so non-idempotent writes are never retried on a timeout
  or a 5xx — a repeat would mean a duplicate listing, or a second email to a buyer.

[Unreleased]: https://github.com/efecim1snn/etsykit/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/efecim1snn/etsykit/releases/tag/v0.1.0
