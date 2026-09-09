# etsykit

[![CI](https://github.com/efecim1snn/etsykit/actions/workflows/ci.yml/badge.svg)](https://github.com/efecim1snn/etsykit/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)
[![Licence: MIT](https://img.shields.io/badge/licence-MIT-green)](LICENSE)
[![Etsy Open API v3](https://img.shields.io/badge/Etsy-Open%20API%20v3-orange)](https://developers.etsy.com/documentation/)

Open-source command line automation for Etsy sellers, built on the official
**Etsy Open API v3**. Bulk listing management, order and tracking sync, and SEO
analysis — running locally, on your own machine, against your own Etsy app.

There is no hosted service, no account, and no middleman. You create an Etsy API
app, paste the keystring into a `.env` file, and everything runs from your terminal.
Your data never leaves your computer.

```bash
etsykit listings pull -o my-listings.csv     # export what you have
etsykit listings push new-products.csv       # create 200 drafts from a spreadsheet
etsykit orders pull --unshipped -o today.csv # today's orders to fulfil
etsykit orders ship tracking.csv             # upload tracking, notify every buyer
etsykit seo audit                            # score every listing, worst first
etsykit seo keywords "ceramic mug"           # what actually ranks, and why
```

---

## Contents

- [Why this exists](#why-this-exists)
- [Install](#install)
- [Getting an Etsy API key](#getting-an-etsy-api-key)
- [First run](#first-run)
- [Bulk listings](#bulk-listings)
- [Orders and tracking](#orders-and-tracking)
- [SEO](#seo)
- [Command reference](#command-reference)
- [How it behaves](#how-it-behaves)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

---

## Why this exists

Most Etsy tools are SaaS: monthly fee, your shop token on someone else's server,
and a black box between you and the API. etsykit is the opposite — a small Python
package you can read end to end in an afternoon. Everyone runs their own copy with
their own credentials, so nobody pays for anybody else's usage.

**What it does not do:** it does not scrape Etsy. Every number it reports comes from
the official API. It also does not invent search volume figures — Etsy does not
publish them, and any tool that shows them is guessing. What `seo keywords` gives you
is measured from the listings Etsy actually returns for a term.

---

## Install

Requires Python 3.9 or newer.

> **Setting up for the first time? Read [SETUP.md](SETUP.md)** — it lists every
> prerequisite and why each one is not optional, in English and Turkish. Or just run
> **`etsykit setup`**, which walks the list, asks about the parts no program can check,
> and tells you the single next command to run.

```bash
git clone https://github.com/efecim1snn/etsykit.git
cd etsykit
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e .
```

Check it:

```bash
etsykit --version
```

---

## Getting an Etsy API key

1. Go to **<https://www.etsy.com/developers/your-apps>** and click *Create a New App*.
2. Fill in the form. For personal use on your own shop, describe what you are building
   honestly — "personal tools for managing my own shop listings and orders" is fine.
3. Once approved you get a **Keystring** and a **Shared secret**. You need **both**.

   > Every v3 request must carry them colon-joined in the `x-api-key` header, including
   > the unauthenticated ones. With the keystring alone Etsy replies
   > `403 {"error":"Invalid API key: should be in the format 'keystring:shared_secret'."}`
   >
   > This trips people up because PKCE is described as removing the client secret — and
   > it does, from the **token exchange** (`client_id` is the bare keystring). It does
   > not remove the shared secret from the **API key header**. etsykit joins them for you;
   > you just set `ETSY_KEYSTRING` and `ETSY_SHARED_SECRET`.
4. In the app settings, add a **callback URL**. Etsy's own settings screen states the
   rules, and they are narrower than the prose docs suggest:

   > - Must start with `http://` or `https://`
   > - Host must be a domain name (e.g. `example.com`)
   > - **IP addresses are not allowed** (e.g. `127.0.0.1`)

   `localhost` is a domain name, so **a local callback works** — which makes this the
   easy path. Register:

   ```
   http://localhost:3003/oauth/redirect
   ```

   and put the identical string in `.env` as `ETSY_REDIRECT_URI`. etsykit starts a
   one-shot listener on that port and catches the code for you.

   > Etsy's narrative documentation says the callback "must implement TLS and use an
   > `https://` prefix". Taken literally that rules out a local listener — but the app
   > settings screen accepts `http://localhost:PORT/...`, and that is what is actually
   > enforced. Use `127.0.0.1` and it *will* be rejected; that is the real constraint.

   Any other host works too: Etsy redirects your browser there, that page does not need
   to exist, and you paste the address back in once (`--paste` forces this flow).

> **Approval times vary.** Personal-use apps are usually approved quickly; apps that
> ask for broad commercial distribution take longer.
>
> **While you wait**, `etsykit listings push --dry-run` and `etsykit orders ship --dry-run`
> validate your CSVs entirely offline — no key, no login. You can have 300 products
> checked and ready before your app is approved. Once you have a keystring,
> `etsykit seo keywords` works too, without logging in.

---

## First run

```bash
etsykit init
```

It asks for your keystring, your shared secret and your callback URL, writes a `.env`
with `0600` permissions, and checks the credential against Etsy before you go further.
**The shared secret is typed hidden** — it does not appear on screen or in your shell
history. Nothing is sent anywhere except Etsy.

```
Keystring: abc123def456ghi789jkl012
Shared secret:
Redirect URI (must match a callback registered on your app) [http://localhost:3003/oauth/redirect]:
✓ Wrote .env (keystring abc123…, shared secret 10 chars)
✓ Etsy accepted the credential.
```

Prefer to write the file yourself? `cp .env.example .env` and fill in the three values.

Verify your setup before trusting it with anything bulk:

```bash
etsykit doctor
```

```
✓ App credentials found (keystring abc123…, shared secret 10 chars)
✓ Redirect URI looks valid (http://localhost:3003/oauth/redirect)
  rate limit:   4 req/sec
✓ API reachable and keystring accepted
! No token stored — only `seo keywords` will work. Run: etsykit auth login
```

Then authorise:

```bash
etsykit auth login
```

A browser opens and you approve the scopes. With a `localhost` callback, etsykit catches
the redirect itself and you are done:

```
Listening on port 3003 for the redirect to http://localhost:3003/oauth/redirect ...
✓ Authorised. Token saved to /home/you/.etsykit/token.json
  scopes: shops_r listings_r listings_w transactions_r transactions_w
  shop:   YourShop (id 12345678)
```

With any other callback host, Etsy sends the browser to your registered URL — that page
does not have to load — and you paste the address from the bar back into the terminal.

The token is saved to `~/.etsykit/token.json` with `0600` permissions. Access tokens
last an hour and etsykit refreshes them automatically; the refresh token lasts 90 days,
so you do this once a quarter at most.

```bash
etsykit auth status     # who am I, which shop, how long is the token good for
etsykit shop info       # shop id, currency, listing counts
```

### Scopes

The default is the minimum needed for everything in this tool:

| Scope | Used for |
|---|---|
| `shops_r` | discovering your shop; required even for `auth status` |
| `listings_r` | reading your listings (`listings pull`, `seo audit`) |
| `listings_w` | creating and updating listings, uploading images |
| `transactions_r` | reading orders (`orders pull`) |
| `transactions_w` | submitting tracking numbers (`orders ship`) |

If you only want read access, narrow it in `.env` before logging in:

```bash
ETSY_SCOPES=shops_r listings_r transactions_r
```

There is deliberately **no `listings_d`** — etsykit never deletes a listing.

---

## Bulk listings

### The CSV

```bash
etsykit listings template -o listings.csv
```

One row per listing. Two rules:

- **`listing_id` empty → create.** **`listing_id` filled → update.**
- Multi-value cells (`tags`, `materials`, `images`) are separated by `|`, not commas,
  so a tag containing a comma survives a trip through Excel.

| Column | Required to create | Notes |
|---|---|---|
| `listing_id` | — | Leave blank to create a new draft |
| `title` | ✔ | Max 140 characters |
| `description` | ✔ | |
| `price` | ✔ | `19.90` or `19,90` both work |
| `quantity` | ✔ | |
| `who_made` | ✔ | `i_did`, `someone_else`, `collective` |
| `when_made` | ✔ | `made_to_order`, `2020_2026`, `2010_2019`, … |
| `taxonomy_id` | ✔ | Find it with `etsykit shop taxonomy <word>` |
| `shipping_profile_id` | ✔ for physical | Find it with `etsykit shop profiles` |
| `type` | — | `physical` (default), `download`, `both` |
| `tags` | — | Max 13, each max 20 chars |
| `materials` | — | Max 13 |
| `images` | — | Paths **relative to the CSV file**, in display order |
| `state` | — | Update only: `active` or `inactive` |

Get the IDs you need:

```bash
etsykit shop profiles                 # shipping_profile_id, return_policy_id, shop_section_id
etsykit shop taxonomy "mug"           # taxonomy_id, ranked with leaf categories first
```

> [`examples/listings.csv`](examples/listings.csv) ships with a **placeholder**
> `shipping_profile_id` of `123456789` so that it passes `--dry-run` out of the box.
> Replace it with a real id from `etsykit shop profiles` before pushing for real, or
> Etsy will reject the row.

### Validate, then push

Always dry-run first. It validates every row locally — title lengths, tag charset and
count, enum values, missing image files — and sends nothing.

```bash
etsykit listings push listings.csv --dry-run
```

```
· row 2  create: Handmade Ceramic Coffee Mug (11 fields, 2 image(s))
✗ row 3  Wooden Lamp — tag 'scandinavian minimalist lamp' is 28 chars, max 20
· row 4  create: Linen Table Runner (10 fields, 1 image(s))

✓ Dry run: 2 row(s) valid, 1 with problems. Nothing was sent.
```

Fix row 3, then push for real:

```bash
etsykit listings push listings.csv --out results.csv
```

**New listings are always created as drafts.** Nothing goes public until you publish
it from your Etsy dashboard — so a mistake in a 300-row CSV is recoverable.
`results.csv` contains the new `listing_id` for every created row; paste that column
back into your source CSV and subsequent pushes become updates.

**The whole file is validated before anything is sent.** If any row fails, the run stops
with nothing written — because discovering that row 40 is invalid *after* rows 1–39 became
real drafts leaves your shop half-populated from a file you would never have pushed.
Fix the reported rows and run again, or pass `--partial` to push the valid ones anyway.

If a listing is created but one of its images fails to upload, the row is reported as
**`partial`**, not as an error: the draft exists in your shop and you need to know about
it. etsykit holds no delete scope, so it cannot undo the create — it tells you instead.

### Round-tripping existing listings

```bash
etsykit listings pull -o current.csv        # edit titles/tags in a spreadsheet
etsykit listings push current.csv           # push the edits back
```

`pull` writes the same columns `push` reads, with `listing_id` already filled in.

> `price` and `quantity` are **not** sent on updates. On a listing with variations they
> live in Etsy's separate inventory endpoint, and patching them here would flatten your
> variation pricing. Change those in Etsy, or open an issue if you need bulk inventory.

---

## Drop designs, get drafts

For print-on-demand: put designs in a folder, get composited mockups and a ready-to-push
CSV. No spreadsheet to fill in by hand.

```bash
etsykit drop init                                # creates ~/Desktop/Etsy Studio
etsykit drop template --from-listing 1234567890  # copy settings from a listing you built
etsykit drop run                                 # designs in → review.csv out
```

**You build the first listing yourself, in Etsy, properly.** Everything after copies it.
That is not laziness on the tool's part: `taxonomy_id`, `shipping_profile_id`,
`return_policy_id`, `who_made`, `when_made`, processing times and price are decisions
about a business, not facts about a picture. Guessing them would put wrong listings in a
real shop.

The workspace is three folders:

| Folder | What goes in it |
|---|---|
| `1-MOCKUPS` | Your mockup templates — a blank shirt, mug, poster. Once. |
| `2-PRODUCTS` | The designs you want listed. This is the one you use every time. |
| `3-DRAFTS` | What comes out: composited images and `review.csv`. |

`drop run` composites each design onto every mockup, appends the flat artwork, works out
the product concept, researches it against listings that actually rank, and writes titles
and 13 tags inside Etsy's limits. **Nothing is sent to Etsy.** Check `review.csv`, then:

```bash
etsykit listings push "3-DRAFTS/2026-09-07-212841/review.csv" --dry-run
etsykit listings push "3-DRAFTS/2026-09-07-212841/review.csv"      # creates drafts
```

Print areas are stored as **fractions** of the mockup, not pixels, in
`1-MOCKUPS/positions.json`. One calibrated rectangle therefore covers every sibling
mockup of the same dimensions, and a sensible default works before you calibrate anything.

Two things it will tell you rather than hide:

- **A filename it cannot read is skipped, not guessed.** `mountain-sunset.png` gives a
  concept; `IMG_2043.png` does not, and inventing a confident title for it would put the
  wrong listing in your shop. Files inside a named subfolder fall back to the folder name.
- **Thin or absent market data is stated on the row.** Without research the titles are
  shorter and fewer of the 13 tag slots fill — and the CSV says so in its `warnings`
  column instead of padding them out with something invented.

The drop flow never writes a `listing_id`, and Etsy only accepts a state change on an
update — so it is structurally incapable of publishing anything.

---

## Orders and tracking

```bash
etsykit orders pull --since 30d -o orders.csv
etsykit orders pull --unshipped -o to-ship.csv
```

`--since` accepts `30d`, `6w`, `3m`, `1y`, or a date like `2026-01-01`.

One row per order, with line items collapsed into a readable cell and the shipping
address split into its own columns.

> ⚠️ **This file contains your customers' personal data** — names, email addresses,
> postal addresses and gift messages. Do not commit it, paste it into an issue, or share
> it. `.gitignore` covers `*.csv` for exactly this reason, but a file you move elsewhere
> is no longer protected.

### Uploading tracking

Add `tracking_code` and `carrier_name` columns (the exported file already has
`receipt_id`), or start from [`examples/tracking.csv`](examples/tracking.csv):

```csv
receipt_id,tracking_code,carrier_name,note_to_buyer,send_bcc
3021456789,1Z999AA10123456784,ups,Thanks! On its way.,false
```

`carrier_name` must be a value Etsy recognises for your shipping origin:

```bash
etsykit orders carriers --country TR
etsykit orders ship tracking.csv --dry-run --country TR   # validate carriers too
etsykit orders ship tracking.csv
```

> **This one is not reversible.** Etsy emails every buyer and marks each order shipped.
> etsykit asks for confirmation first and supports `--dry-run`; use both.

---

## SEO

### Audit your own listings

```bash
etsykit seo audit -o seo-report.csv
```

Scores every listing out of 100 and prints the weakest first. The checks are Etsy's
documented limits plus how its search surface actually behaves:

- **Tags** — unused slots out of 13, over-length tags, exact duplicates, near-duplicates
  that burn two slots on one query (`gift` / `gifts`), too many single-word tags,
  and tags sharing no word with the title.
- **Titles** — length, keyword buried past the ~40-character truncation point,
  repeated words, comma chains, shouting.
- **Descriptions** — thin content, and openings that repeat none of the title keywords
  (that first paragraph is the snippet Google shows).
- **Housekeeping** — missing materials, auto-renew off, expired listings.

```
  score  listing_id  title                            issues
     45  1234567890  Mug                              title is only 3 chars…; 4/13 tags used…
     62  1234567891  Handmade Ceramic Coffee Mug…     9/13 tags used — 4 slot(s) left…
```

### Research a keyword

```bash
etsykit seo keywords "ceramic mug" --sample 300 -o mug-tags.csv
```

Samples the listings Etsy ranks for a term and reports what they have in common:
tag frequency with the share of listings using each, recurring title phrases
(1–3 word n-grams), the price band, and the most-favourited listings in the sample.

**This works with only your keystring — no login required.**

### Both at once, for one listing

```bash
etsykit seo suggest 1234567890
```

Audits that listing, then researches its own keyword and lists tags used by ranking
competitors that you are not using yet, with the share of ranking listings that use each.

Add tags only if they honestly describe your item. Irrelevant tags pull in traffic that
does not convert, and Etsy weights conversion heavily.

---

## Command reference

| Command | What it does |
|---|---|
| `etsykit init` | Write `.env` interactively and verify the credential |
| `etsykit doctor` | Check config, key and connectivity |
| `etsykit auth login` | OAuth consent flow (PKCE) |
| `etsykit auth status` | Token, scopes, shop, remaining daily quota |
| `etsykit auth refresh` | Force a token refresh |
| `etsykit auth logout` | Delete the stored token |
| `etsykit shop info` | Shop identifiers and headline numbers |
| `etsykit shop profiles` | Shipping profiles, return policies, sections |
| `etsykit shop taxonomy <word>` | Find a `taxonomy_id` |
| `etsykit drop init` | Create the designs-in workspace folder |
| `etsykit drop template` | Copy settings from a listing you built by hand |
| `etsykit drop run` | Designs → mockups, titles, tags → `review.csv` |
| `etsykit listings template` | Write a starter CSV |
| `etsykit listings pull` | Export listings to CSV |
| `etsykit listings push` | Bulk create/update from CSV |
| `etsykit orders pull` | Export orders to CSV |
| `etsykit orders carriers` | Valid `carrier_name` values for a country |
| `etsykit orders ship` | Bulk tracking upload |
| `etsykit seo audit` | Score all listings |
| `etsykit seo keywords` | Market research for a term |
| `etsykit seo suggest` | Audit + tag suggestions for one listing |

Every command supports `--help`.

---

## How it behaves

**Rate limiting.** Limits are **per app**, and your app's real allowance is printed on its
row at [your-apps](https://www.etsy.com/developers/your-apps). A **Personal Access** app
gets **5 QPS / 5,000 per day** — not the 10/sec, 10,000/day the general docs quote, which
applies to apps granted commercial access. etsykit defaults to **4/second** so it is safe
on the personal tier; raise it with `ETSYKIT_RATE_PER_SEC` if your app is allowed more.
`auth status` shows the remaining daily quota.

**Retries.** `429` is retried on any request — it means Etsy refused, not that it acted.
`5xx` and network errors are retried **only on reads**. Etsy has no idempotency key, so a
write that may have landed is never repeated: a retried `POST` would mean a duplicate
draft, or a second "your order shipped" email to the same buyer. Those are reported
instead, with a warning that the request may have been accepted. Up to 5 attempts,
exponential backoff with jitter, honouring `Retry-After`. Other `4xx` errors are not
retried — they are reported with a hint about the likely cause.

**Token refresh.** Handled transparently, including a re-refresh if a token expires
mid-batch.

**All-or-nothing by default.** `listings push` validates every row before it sends
anything. One bad row stops the run with nothing written; `--partial` opts back into
row-by-row. You get a per-row report and a non-zero exit code if anything failed. For
cron or CI, pass `--yes` (`-y`) to `listings push` and `orders ship` — without it they
stop at an interactive confirmation and a scheduled job would hang.

**Local validation is strict about numbers.** A negative price, a zero price, a negative
quantity or a fractional `quantity` like `3.9` are all rejected here rather than rounded
or forwarded. On an update, fields Etsy's `updateListing` does not accept — `price` and
`quantity` among them — are reported as ignored instead of silently dropped.

**Encoding.** CSVs are read and written as UTF-8 with BOM so Excel on Windows does not
mangle `ç`, `ğ`, `ü`, `é` or `ß`. Prices accept a decimal comma.

**Secrets.** The keystring lives in `.env` (git-ignored). The token lives in
`~/.etsykit/token.json`, written `0600`. Neither is ever printed in full.

### Development

```bash
pip install -e ".[dev]"
pytest          # unit tests — no network, no credentials needed
ruff check .
```

The test suite covers CSV validation, Etsy's tag and title rules, form encoding,
receipt flattening and the SEO scoring, so you can refactor without a live shop.

---

## Troubleshooting

**`ETSY_KEYSTRING is not set`** — copy `.env.example` to `.env` and paste your keystring,
or export it in your shell.

**`Etsy does not accept IP addresses in a callback URL`** — use `localhost`, not
`127.0.0.1`. Etsy requires a domain-name host; `localhost` qualifies, a bare IP does not.

**Etsy shows "redirect_uri is not valid"** — the callback registered on your app does not
match `ETSY_REDIRECT_URI` byte for byte. Compare them character by character, including
the scheme, the port, any trailing slash, and the path.

**`Cannot listen on 127.0.0.1:3003`** — something else holds that port. Pick another,
change it in **both** `.env` and your Etsy app's callback list, or use `--paste`.

**The callback page shows an error / does not load** — harmless when you are using the
paste flow. The authorization code is in the browser's address bar; copy the whole
address and paste it in.

**`403 Forbidden`** — usually a missing scope. `etsykit auth status` shows what you granted;
widen `ETSY_SCOPES` and run `etsykit auth login` again.

**`400` on listing create** — the most common causes are a `taxonomy_id` that is not a leaf
category, a missing `shipping_profile_id` on a physical listing, or a shop that requires a
`return_policy_id`. Run with `--dry-run` first; it catches most of these locally.

**Turkish/German characters look wrong in Excel** — your spreadsheet saved the file as
something other than UTF-8. Re-export as UTF-8 CSV; etsykit always writes UTF-8 with BOM.

---

## Contributing

Issues and pull requests welcome — see **[CONTRIBUTING.md](CONTRIBUTING.md)** for setup,
the rules that matter, and where help would go furthest. You need no Etsy account and no
network connection to contribute: the whole test suite is offline by design.

Useful directions: inventory and variations (`updateListingInventory`), digital
downloads, shop section management, listing translations, and a renewal helper.

- **[SECURITY.md](SECURITY.md)** — what etsykit stores, where, and how to report a
  vulnerability privately
- **[CHANGELOG.md](CHANGELOG.md)** — release history, including the Etsy API gotchas
  this project had to establish the hard way
- **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)**

Please keep the no-scraping rule: official API endpoints only.

---

## Licence

MIT — see [LICENSE](LICENSE). Trademark and third-party notices are in
[NOTICE.md](NOTICE.md).

etsykit is an independent project, **not affiliated with or endorsed by Etsy, Inc.**
You remain responsible for complying with the
[Etsy API Terms of Use](https://www.etsy.com/legal/api) and Etsy's seller policies.
