"""Turns raw chat text into things we can look up. Pure functions, no network."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from urllib.parse import parse_qs, urlparse

MAX_LOOKUPS_PER_MESSAGE = 10


@dataclass(frozen=True)
class SearchQuery:
    text: str
    kgmid: str | None = None  # Google's id of the movie, when the query comes from a Google link

    @property
    def label(self) -> str:
        return self.text


@dataclass(frozen=True)
class ImdbRef:
    imdb_id: str

    @property
    def label(self) -> str:
        return f"https://www.imdb.com/title/{self.imdb_id}/"


@dataclass(frozen=True)
class TmdbRef:
    media_type: str  # "movie" or "tv"
    tmdb_id: int

    @property
    def label(self) -> str:
        return f"https://www.themoviedb.org/{self.media_type}/{self.tmdb_id}"


@dataclass(frozen=True)
class UnknownLink:
    """A link we can't read directly (g.co/kgs/…, share.google/…, bit.ly/…) - follow its redirects."""

    url: str

    @property
    def label(self) -> str:
        return self.url


Lookup = SearchQuery | ImdbRef | TmdbRef | UnknownLink


@dataclass(frozen=True)
class SearchVariant:
    title: str
    year: int | None = None


URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"]+", re.IGNORECASE)
IMDB_ID_RE = re.compile(r"\b(tt\d{6,10})\b")
TMDB_PATH_RE = re.compile(r"^/(?:[a-z]{2}(?:-[A-Z]{2})?/)?(movie|tv)/(\d+)")
GOOGLE_HOST_RE = re.compile(r"(?:^|\.)google\.[a-z]{2,3}(?:\.[a-z]{2})?$")
GOOGLE_SEARCH_PATHS = {"", "/", "/search", "/webhp"}
YEAR_RE = re.compile(r"[(\[]?\b((?:18|19|20)\d{2})\b[)\]]?")
TRAILING_JUNK = ").,!?;:»\"'"

# Words people (and Google queries) add around a title. Only used in a *second* search attempt,
# so titles like "Scary Movie" or "The Truman Show" still match on the first, literal attempt.
NOISE_WORDS = {
    "movie", "movies", "film", "films", "trailer", "watch", "online", "imdb", "full", "hd",
    "series", "tv", "review", "cast",
    "фільм", "фильм", "кіно", "кино", "трейлер", "дивитися", "дивитись", "смотреть", "онлайн",
    "серіал", "сериал", "мультфільм", "мультфильм",
}


def parse_message(text: str) -> list[Lookup]:
    """Every non-empty line is a movie name, unless it contains links - then the links are used."""
    lookups: list[Lookup] = []
    for line in text.splitlines():
        line = " ".join(line.split())
        if not line or line.startswith("/"):
            continue
        urls = URL_RE.findall(line)
        if not urls:
            lookups.append(SearchQuery(line))
            continue
        for url in urls:
            lookup = parse_url(url)
            if lookup is not None:
                lookups.append(lookup)
    return list(dict.fromkeys(lookups))[:MAX_LOOKUPS_PER_MESSAGE]


def parse_url(url: str) -> Lookup | None:
    url = url.rstrip(TRAILING_JUNK)
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    params = parse_qs(parsed.query)

    if host == "imdb.com" or host.endswith(".imdb.com"):
        match = IMDB_ID_RE.search(parsed.path)
        return ImdbRef(match.group(1)) if match else None

    if host == "themoviedb.org" or host.endswith(".themoviedb.org"):
        match = TMDB_PATH_RE.match(parsed.path)
        return TmdbRef(match.group(1), int(match.group(2))) if match else None

    if GOOGLE_HOST_RE.search(host):
        # google.com/url?q=<target>, consent.google.com/?continue=<target>, google.com/sorry?continue=<target>
        for wrapper_param in ("continue", "url"):
            if target := _first(params, wrapper_param):
                return parse_url(target)
        query = _first(params, "q")
        if query and parsed.path == "/url":
            return parse_url(query)
        if query and parsed.path in GOOGLE_SEARCH_PATHS:
            return SearchQuery(" ".join(query.split()), _first(params, "kgmid"))
        # Not a search page yet, e.g. share.google/<code> -> google.com/share.google?q=<code> -> google.com/search?q=<title>
        return UnknownLink(url)

    return UnknownLink(url)


def search_variants(text: str, today: date | None = None) -> list[SearchVariant]:
    """Search attempts in order of preference: "Dune 2021 film" -> ("Dune film", 2021), ("Dune 2021 film"), ("Dune", 2021)."""
    raw = " ".join(text.split())
    title, year = split_year(raw, today)
    variants = []
    if year:
        variants.append(SearchVariant(title, year))
    variants.append(SearchVariant(raw))
    if cleaned := strip_noise(title):
        variants.append(SearchVariant(cleaned, year))

    unique: dict[tuple[str, int | None], SearchVariant] = {}
    for variant in variants:
        if variant.title:
            unique.setdefault((variant.title.casefold(), variant.year), variant)
    return list(unique.values())


def split_year(text: str, today: date | None = None) -> tuple[str, int | None]:
    """'Inception (2010)' -> ('Inception', 2010). Keeps titles like '1917', '2001: A Space Odyssey', 'Blade Runner 2049'."""
    max_year = (today or date.today()).year + 3
    for match in reversed(list(YEAR_RE.finditer(text))):
        year = int(match.group(1))
        if match.start() == 0 or not 1888 <= year <= max_year:
            continue
        title = (text[: match.start()] + " " + text[match.end():]).strip(" -–—,:|")
        title = " ".join(title.split())
        if title:
            return title, year
    return text, None


def strip_noise(text: str) -> str:
    words = [w for w in re.split(r"[\s\-–—|:,]+", text) if w and w.strip("()[]").casefold() not in NOISE_WORDS]
    return " ".join(words).strip()


def normalize_title(title: str) -> str:
    """Comparable form of a title: case, accents, punctuation and '&' vs 'and' don't matter."""
    title = unicodedata.normalize("NFKD", title.casefold())
    title = "".join(c for c in title if not unicodedata.combining(c))
    title = title.replace("&", " and ")
    title = re.sub(r"[^\w\s]|_", " ", title)
    return " ".join(title.split())


def _first(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    return values[0] if values else None
