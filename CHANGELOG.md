# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] — 2026-09-08

### Added

- **`etsykit drop` — designs in a folder, drafts out.** For print-on-demand sellers who
  do not want to fill in a spreadsheet.
  - `drop init` creates a three-folder workspace (`1-MOCKUPS`, `2-PRODUCTS`, `3-DRAFTS`)
    with a README in Turkish and English.
  - `drop template --from-listing <id>` copies category, shipping profile, return
    policy, price, processing times and materials from one listing you built by hand.
    Those cannot be derived from an image, and guessing them would put wrong listings in
    a real shop.
  - `drop run` composites each design onto every mockup with Pillow, appends the flat
    artwork, works out the product concept, researches it, and writes titles and 13 tags
    inside Etsy's limits into a `review.csv` that `listings push` already consumes.
- **Print areas are stored as fractions of the mockup, not pixels**, so one calibrated
  rectangle covers every sibling mockup of the same size and a sensible default works
  before anything is calibrated. It also makes the compositor testable in CI on
  generated images, with no assets in the repository.
- **A filename that carries no concept is skipped, not guessed.** `IMG_2043.png` is
  reported with a reason instead of becoming a confidently-wrong title. Files in a named
  subfolder fall back to the folder name.
- **Thin or absent market data is stated on the row** rather than padded out. Without
  research the titles are shorter and fewer tag slots fill, and the CSV says so.
- New dependency: **Pillow**, which ships prebuilt wheels everywhere and needs no
  compiler — the reason the image half is Python rather than a Node/Sharp sidecar.

### Fixed

From an external offline code review (7 September 2026) that ran the tool against mock
transports and observed sixteen behaviours. Nine were defects:

- **Keyword shares were counted wrong.** Tag and title-phrase counts were per
  *occurrence*, not per *listing*, while the interface labelled them "appears in N of M
  listings". A title reading "ceramic mug ceramic mug" counted twice, so a share could
  exceed 100%. Now counted per distinct listing, which is what the label always claimed.
- **`listings push` wrote row by row without validating the file first.** Row 1 could
  become a real draft before row 40 failed validation, leaving a shop half-populated
  from a file the seller would never have pushed. The whole file is now validated
  first; `--partial` opts back into the old behaviour.
- **A created draft could be reported as nothing at all.** When the listing was created
  and an image upload then failed, the row was marked an error and the created count
  stayed at zero — while the draft sat in the shop. Now reported as `partial`, with the
  listing id and an explicit note that it exists.
- **`quantity=3.9` silently became 3.** Fractional values are now rejected.
- **Negative and zero values passed local validation.** `price=-5`, `price=0` and
  `quantity=-3` reached Etsy to be refused there. Lower bounds are enforced locally.
- **`--no-images` still failed rows for missing image files** it was never going to upload.
- **The SEO audit ignored more than 13 tags**, so an over-limit listing could score 100
  even though the listing validator has always rejected it.
- **Tag suggestions were not capped by free slots.** A listing with 12 tags was offered
  13 additions; only one can fit. Suggestions are now split into what fits and what
  would need a swap.
- **Update rows dropped fields silently.** Editing `price` in a CSV and pushing an
  update reported success and changed nothing. Ignored fields are now named.

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

[Unreleased]: https://github.com/efecim1snn/etsykit/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/efecim1snn/etsykit/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/efecim1snn/etsykit/releases/tag/v0.1.0
