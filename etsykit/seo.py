"""SEO analysis.

Two independent things live here:

*Audit* looks only at your own listings and checks them against Etsy's documented
limits plus the mechanics of how Etsy search reads a listing — unused tag slots,
titles that bury the keyword past the truncation point, tags that no longer appear
anywhere in the title.

*Keyword research* reads the public marketplace through findAllListingsActive (the
one endpoint that needs no OAuth token) and reports what the listings ranking for a
term actually have in common: their tags, their title phrases, their price band.

Neither invents search-volume numbers. Etsy does not expose them, and any tool
claiming otherwise is guessing. What you get here is measured from real listings.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .client import EtsyClient
from .config import MAX_TAG_LEN, MAX_TAGS, MAX_TITLE_LEN

# Etsy truncates titles in search results and on mobile cards around here, so the
# keyword a buyer scans for should land inside this window.
TITLE_VISIBLE_CHARS = 40
TITLE_MIN_USEFUL = 40
DESCRIPTION_MIN_USEFUL = 160

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "it",
    "of", "on", "or", "that", "the", "this", "to", "with", "your", "you", "my", "our",
    "can", "will", "not", "but", "all", "any", "have", "has", "was", "were", "into",
    "ve", "ile", "bir", "bu", "icin", "için", "da", "de", "en",
}

_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?|\d+", re.UNICODE)

SEVERITY_WEIGHT = {"error": 25, "warn": 10, "info": 3}


@dataclass
class Issue:
    code: str
    severity: str  # error | warn | info
    message: str


@dataclass
class Audit:
    listing_id: int
    title: str
    url: str = ""
    issues: list[Issue] = field(default_factory=list)

    @property
    def score(self) -> int:
        penalty = sum(SEVERITY_WEIGHT.get(i.severity, 5) for i in self.issues)
        return max(0, 100 - penalty)

    @property
    def grade(self) -> str:
        score = self.score
        if score >= 85:
            return "good"
        if score >= 60:
            return "fair"
        return "poor"

    def summary(self) -> str:
        return "; ".join(i.message for i in self.issues) or "no issues found"


def words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text or "")]


def content_words(text: str) -> list[str]:
    return [w for w in words(text) if w not in STOPWORDS and len(w) > 2]


def audit_listing(listing: dict[str, Any]) -> Audit:
    title = (listing.get("title") or "").strip()
    description = (listing.get("description") or "").strip()
    tags = [t for t in (listing.get("tags") or []) if t]
    materials = listing.get("materials") or []

    result = Audit(
        listing_id=int(listing.get("listing_id") or 0),
        title=title,
        url=listing.get("url", ""),
    )
    add = result.issues.append

    # --- title -----------------------------------------------------------------
    if not title:
        add(Issue("title.missing", "error", "title is empty"))
    else:
        if len(title) > MAX_TITLE_LEN:
            add(Issue("title.too_long", "error",
                      f"title is {len(title)} chars, Etsy caps at {MAX_TITLE_LEN}"))
        elif len(title) < TITLE_MIN_USEFUL:
            add(Issue("title.too_short", "warn",
                      f"title is only {len(title)} chars — short titles cover fewer queries"))

        head_words = set(content_words(title[:TITLE_VISIBLE_CHARS]))
        tail_words = set(content_words(title[TITLE_VISIBLE_CHARS:]))
        if tail_words and not head_words:
            add(Issue("title.front_empty", "warn",
                      f"the first {TITLE_VISIBLE_CHARS} chars carry no keyword — that is all "
                      "a buyer sees before the title is truncated"))

        counts = Counter(content_words(title))
        stuffed = [w for w, c in counts.items() if c >= 3]
        if stuffed:
            add(Issue("title.repetition", "warn",
                      f"repeated {'word' if len(stuffed) == 1 else 'words'} in title: "
                      f"{', '.join(sorted(stuffed))}"))

        if title.count(",") > 6:
            add(Issue("title.comma_spam", "info",
                      f"{title.count(',')} commas — long keyword chains read as spam to buyers"))

        shouty = [w for w in re.findall(r"\b[A-ZÇĞİÖŞÜ]{4,}\b", title) if w.isupper()]
        if len(shouty) >= 2:
            add(Issue("title.caps", "info", f"ALL-CAPS words in title: {', '.join(shouty[:3])}"))

    # --- tags ------------------------------------------------------------------
    if not tags:
        add(Issue("tags.missing", "error", "no tags — Etsy gives you 13 free query slots"))
    else:
        if len(tags) < MAX_TAGS:
            add(Issue("tags.unused", "warn",
                      f"{len(tags)}/{MAX_TAGS} tags used — {MAX_TAGS - len(tags)} slot(s) left on the table"))

        too_long = [t for t in tags if len(t) > MAX_TAG_LEN]
        if too_long:
            add(Issue("tags.too_long", "error",
                      f"tag(s) over {MAX_TAG_LEN} chars: {', '.join(too_long[:3])}"))

        lowered = [t.lower().strip() for t in tags]
        dupes = {t for t in lowered if lowered.count(t) > 1}
        if dupes:
            add(Issue("tags.duplicate", "error", f"duplicate tags: {', '.join(sorted(dupes))}"))

        near = _near_duplicates(lowered)
        if near:
            add(Issue("tags.near_duplicate", "info",
                      "near-duplicate tags compete with each other: "
                      + ", ".join(f"{a}/{b}" for a, b in near[:3])))

        single = [t for t in tags if len(t.split()) == 1]
        if tags and len(single) / len(tags) > 0.6:
            add(Issue("tags.single_word", "warn",
                      f"{len(single)}/{len(tags)} tags are single words — multi-word "
                      "long-tail tags face far less competition"))

        title_words = set(content_words(title))
        orphans = [t for t in tags if not (set(content_words(t)) & title_words)]
        if title and len(orphans) > len(tags) / 2:
            add(Issue("tags.title_mismatch", "warn",
                      f"{len(orphans)} tag(s) share no word with the title — Etsy ranks "
                      "listings higher when title and tags reinforce each other"))

    # --- description -----------------------------------------------------------
    if not description:
        add(Issue("description.missing", "error", "description is empty"))
    elif len(description) < DESCRIPTION_MIN_USEFUL:
        add(Issue("description.thin", "warn",
                  f"description is {len(description)} chars — thin descriptions convert poorly"))
    else:
        opening = set(content_words(description[:DESCRIPTION_MIN_USEFUL]))
        if title and not (opening & set(content_words(title))):
            add(Issue("description.opening", "info",
                      "the opening lines repeat none of the title keywords — that snippet is "
                      "what Google shows"))

    # --- everything else --------------------------------------------------------
    if not materials:
        add(Issue("materials.missing", "info", "no materials set — a free, indexed attribute"))
    if listing.get("should_auto_renew") is False:
        add(Issue("renew.off", "info", "auto-renew is off; the listing will expire in 4 months"))
    if listing.get("state") == "expired":
        add(Issue("state.expired", "warn", "listing has expired and is not visible"))

    return result


def _near_duplicates(tags: Sequence[str]) -> list[tuple[str, str]]:
    """Catch pairs like 'gift'/'gifts' that burn two slots on one query."""
    pairs = []
    for i, a in enumerate(tags):
        for b in tags[i + 1:]:
            if a == b:
                continue
            if a.rstrip("s") == b.rstrip("s") or a.replace(" ", "") == b.replace(" ", ""):
                pairs.append((a, b))
    return pairs


def audit_all(client: EtsyClient, *, state: str = "active", max_items: int | None = None) -> list[Audit]:
    return [audit_listing(listing) for listing in client.listings_by_shop(state=state, max_items=max_items)]


# --- market research ------------------------------------------------------------


@dataclass
class MarketReport:
    keyword: str
    sampled: int
    tags: list[tuple[str, int]]
    phrases: list[tuple[str, int]]
    price_min: float | None
    price_median: float | None
    price_max: float | None
    currency: str
    median_favorers: float | None
    top_listings: list[dict[str, Any]]
    # How many of the sampled listings the price band actually covers, and how many
    # distinct currencies turned up. Etsy prices each listing in its own shop's
    # currency, so the band describes one currency, not the whole sample.
    price_sample: int = 0
    currency_count: int = 0

    @property
    def empty(self) -> bool:
        return self.sampled == 0

    @property
    def price_band_is_partial(self) -> bool:
        return self.currency_count > 1


def _price(listing: dict[str, Any]) -> tuple[float | None, str]:
    price = listing.get("price") or {}
    amount, divisor = price.get("amount"), price.get("divisor") or 100
    if not isinstance(amount, (int, float)):
        return None, ""
    return amount / divisor, str(price.get("currency_code", ""))


def ngrams(tokens: Sequence[str], size: int) -> Iterable[str]:
    for i in range(len(tokens) - size + 1):
        window = tokens[i:i + size]
        if any(w in STOPWORDS for w in window):
            continue
        yield " ".join(window)


def research(
    client: EtsyClient,
    keyword: str,
    *,
    sample: int = 200,
    sort_on: str = "score",
    **filters: Any,
) -> MarketReport:
    """Sample the listings Etsy actually returns for a keyword and describe them."""
    listings = list(
        client.search_active_listings(
            keywords=keyword, max_items=sample, sort_on=sort_on, sort_order="desc", **filters
        )
    )

    tag_counter: Counter[str] = Counter()
    phrase_counter: Counter[str] = Counter()
    prices_by_currency: dict[str, list[float]] = {}
    favorers: list[int] = []

    for listing in listings:
        for tag in listing.get("tags") or []:
            cleaned = str(tag).strip().lower()
            if cleaned:
                tag_counter[cleaned] += 1

        tokens = words(listing.get("title") or "")
        for size in (1, 2, 3):
            for gram in ngrams(tokens, size):
                if size == 1 and (gram in STOPWORDS or len(gram) < 3):
                    continue
                phrase_counter[gram] += 1

        price, code = _price(listing)
        if price is not None:
            prices_by_currency.setdefault(code or "?", []).append(price)

        fav = listing.get("num_favorers")
        if isinstance(fav, int):
            favorers.append(fav)

    # A marketplace-wide search returns each listing priced in its own shop's
    # currency. Pooling them would make min/median/max arithmetic over
    # incommensurable numbers, so report the band for the single most common
    # currency and carry the coverage so the caller can say so out loud.
    currency, prices = "", []
    if prices_by_currency:
        currency, prices = max(prices_by_currency.items(), key=lambda kv: len(kv[1]))

    # A phrase that appears once is noise, not a pattern.
    phrases = [(p, c) for p, c in phrase_counter.most_common(400) if c >= max(2, len(listings) // 25)]

    top = sorted(listings, key=lambda x: x.get("num_favorers") or 0, reverse=True)[:10]
    top_rows = []
    for listing in top:
        price, code = _price(listing)
        top_rows.append(
            {
                "listing_id": listing.get("listing_id"),
                "title": listing.get("title", ""),
                "price": f"{price:.2f}" if price is not None else "",
                "currency": code,
                "num_favorers": listing.get("num_favorers", 0),
                "tags": listing.get("tags") or [],
                "url": listing.get("url", ""),
            }
        )

    return MarketReport(
        keyword=keyword,
        sampled=len(listings),
        tags=tag_counter.most_common(40),
        phrases=phrases[:40],
        price_min=min(prices) if prices else None,
        price_median=statistics.median(prices) if prices else None,
        price_max=max(prices) if prices else None,
        currency=currency,
        median_favorers=statistics.median(favorers) if favorers else None,
        top_listings=top_rows,
        price_sample=len(prices),
        currency_count=len(prices_by_currency),
    )


def suggest_tags(report: MarketReport, *, existing: Sequence[str] = ()) -> list[str]:
    """Tags common in the ranking set that this listing does not use yet."""
    have = {t.lower().strip() for t in existing}
    out = []
    for tag, _count in report.tags:
        if tag in have or len(tag) > MAX_TAG_LEN:
            continue
        out.append(tag)
        if len(out) >= MAX_TAGS:
            break
    return out
