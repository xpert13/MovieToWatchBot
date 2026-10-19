"""Finds movies on TMDB (search, posters, descriptions) and their IMDb rating on OMDb."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, replace
from urllib.parse import urljoin

import httpx

from .parsing import (
    ImdbRef,
    Lookup,
    SearchQuery,
    TmdbRef,
    UnknownLink,
    normalize_title,
    parse_url,
    search_variants,
)

log = logging.getLogger(__name__)

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMAGES = "https://image.tmdb.org/t/p/w780"
OMDB_API = "https://www.omdbapi.com/"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
WIKIDATA_USER_AGENT = "MoviesToWatchBot/1.0 (https://github.com/xpert13/MovieToWatchBot)"
KGMID_RE = re.compile(r"^/[mg]/[0-9a-z_]+$")
MAX_REDIRECTS = 5

# When several titles match exactly, also post the less popular ones if they reach these shares of the top one.
MIN_VOTES = 20
VOTES_SHARE = 0.05
POPULARITY_SHARE = 0.3
# A non-exact top result this many times more voted than every exact match is probably what was meant
# ("Godfather" -> also post "The Godfather", not only an obscure film literally called "Godfather").
DOMINANT_FACTOR = 10


@dataclass(frozen=True)
class Candidate:
    media_type: str
    tmdb_id: int
    title: str
    original_title: str
    year: int | None
    vote_count: int
    popularity: float
    other_titles: tuple[str, ...] = ()  # the same movie's title in other languages

    @property
    def titles(self) -> tuple[str, ...]:
        return (self.title, self.original_title, *self.other_titles)

    @classmethod
    def from_tmdb(cls, item: dict, media_type: str) -> Candidate:
        is_movie = media_type == "movie"
        return cls(
            media_type=media_type,
            tmdb_id=item["id"],
            title=item.get("title" if is_movie else "name") or "",
            original_title=item.get("original_title" if is_movie else "original_name") or "",
            year=_year(item.get("release_date" if is_movie else "first_air_date")),
            vote_count=item.get("vote_count") or 0,
            popularity=item.get("popularity") or 0.0,
        )


@dataclass(frozen=True)
class Movie:
    media_type: str
    tmdb_id: int
    title: str
    original_title: str
    year: int | None
    overview: str
    genres: tuple[str, ...]
    runtime_minutes: int | None
    seasons: int | None
    poster_url: str | None
    imdb_id: str | None
    tmdb_rating: float | None
    tmdb_votes: int | None
    imdb_rating: str | None = None
    imdb_votes: int | None = None

    @property
    def tmdb_url(self) -> str:
        return f"https://www.themoviedb.org/{self.media_type}/{self.tmdb_id}"

    @property
    def imdb_url(self) -> str | None:
        return f"https://www.imdb.com/title/{self.imdb_id}/" if self.imdb_id else None


def pick_matches(candidates: list[Candidate], title: str, max_results: int) -> tuple[list[Candidate], bool]:
    """Returns (what to post, whether the title matched exactly).

    Exact title matches all get posted (most popular first) so the user can delete the wrong ones;
    without an exact match we trust TMDB's top result.
    """
    if not candidates:
        return [], False
    wanted = normalize_title(title)
    exact = [c for c in candidates if wanted in {normalize_title(t) for t in c.titles}]
    if not exact:
        return [candidates[0]], False

    exact.sort(key=lambda c: (c.popularity, c.vote_count), reverse=True)
    max_votes = max(c.vote_count for c in exact)
    min_votes = max(MIN_VOTES, max_votes * VOTES_SHARE)
    min_popularity = exact[0].popularity * POPULARITY_SHARE
    picked = [exact[0]] + [c for c in exact[1:] if c.vote_count >= min_votes or c.popularity >= min_popularity]

    dominant = max(candidates[:5], key=lambda c: c.vote_count)
    if dominant not in exact and dominant.vote_count >= DOMINANT_FACTOR * max(max_votes, MIN_VOTES):
        picked = [dominant, picked[0]]  # the famous one was most likely meant - keep just the best literal match next to it
    return picked[:max_results], True


def closest_to_year(candidates: list[Candidate], year: int) -> list[Candidate]:
    """TMDB's year filter also matches re-releases (Dune 1984 was re-released in 2021), so keep the closest premieres."""
    for tolerance in (0, 1):
        if close := [c for c in candidates if c.year is not None and abs(c.year - year) <= tolerance]:
            return close
    return candidates


class TmdbClient:
    def __init__(self, http: httpx.AsyncClient, api_key: str, language: str, include_tv: bool):
        self._http = http
        self._language = language
        self._include_tv = include_tv
        # TMDB gives two kinds of credentials: a short v3 "API key" and a long v4 "Read Access Token" (a JWT).
        if api_key.startswith("eyJ"):
            self._auth_headers, self._auth_params = {"Authorization": f"Bearer {api_key}"}, {}
        else:
            self._auth_headers, self._auth_params = {}, {"api_key": api_key}

    async def _get(self, path: str, **params) -> dict:
        response = await self._http.get(
            TMDB_API + path,
            params={"language": self._language, **self._auth_params, **params},
            headers=self._auth_headers,
        )
        response.raise_for_status()
        return response.json()

    async def search(self, title: str, year: int | None = None) -> list[Candidate]:
        # Results only carry the title in the requested language (and the original one), so search in English too:
        # "Parasite" has to match the movie TMDB calls "Паразити" / "기생충".
        languages = [self._language] if self._language.startswith("en") else [self._language, "en-US"]
        merged: dict[tuple[str, int], Candidate] = {}
        for candidates in await asyncio.gather(*(self._search(title, year, language) for language in languages)):
            for c in candidates:
                key = (c.media_type, c.tmdb_id)
                if key in merged:
                    merged[key] = replace(merged[key], other_titles=merged[key].other_titles + (c.title,))
                else:
                    merged[key] = c
        return list(merged.values())

    async def _search(self, title: str, year: int | None, language: str) -> list[Candidate]:
        if year is None:
            data = await self._get("/search/multi", query=title, include_adult="false", language=language)
            items = [(item, item.get("media_type")) for item in data.get("results", [])]
        else:
            requests = [self._get("/search/movie", query=title, year=year, include_adult="false", language=language)]
            if self._include_tv:
                requests.append(self._get(
                    "/search/tv", query=title, first_air_date_year=year, include_adult="false", language=language,
                ))
            responses = await asyncio.gather(*requests)
            items = [(item, media_type) for media_type, data in zip(("movie", "tv"), responses) for item in data.get("results", [])]

        allowed = {"movie", "tv"} if self._include_tv else {"movie"}
        return [Candidate.from_tmdb(item, media_type) for item, media_type in items if media_type in allowed]

    async def find_by_imdb_id(self, imdb_id: str) -> Candidate | None:
        data = await self._get(f"/find/{imdb_id}", external_source="imdb_id")
        for media_type in ("movie", "tv"):
            if results := data.get(f"{media_type}_results"):
                return Candidate.from_tmdb(results[0], media_type)
        return None

    async def details(self, media_type: str, tmdb_id: int) -> Movie:
        data = await self._get(f"/{media_type}/{tmdb_id}", append_to_response="external_ids,translations")
        is_movie = media_type == "movie"
        name_field = "title" if is_movie else "name"
        translations = (data.get("translations") or {}).get("translations") or []
        # Not every movie is translated into every language. Without a translation TMDB returns the original title
        # (unreadable when it's Chinese or Korean) and no description, so fall back to English - the most complete.
        title = (
            _translation(translations, self._language, name_field)
            or _translation(translations, "en-US", name_field)
            or data.get(name_field)
            or ""
        )
        overview = data.get("overview") or _translation(translations, "en-US", "overview")

        runtime = data.get("runtime") if is_movie else next(iter(data.get("episode_run_time") or []), None)
        return Movie(
            media_type=media_type,
            tmdb_id=tmdb_id,
            title=title,
            original_title=data.get("original_title" if is_movie else "original_name") or "",
            year=_year(data.get("release_date" if is_movie else "first_air_date")),
            overview=overview.strip(),
            genres=tuple(g["name"] for g in data.get("genres", [])),
            runtime_minutes=runtime or None,
            seasons=None if is_movie else data.get("number_of_seasons"),
            poster_url=TMDB_IMAGES + data["poster_path"] if data.get("poster_path") else None,
            imdb_id=data.get("imdb_id") or (data.get("external_ids") or {}).get("imdb_id") or None,
            tmdb_rating=data.get("vote_average") or None,
            tmdb_votes=data.get("vote_count") or None,
        )


class OmdbClient:
    def __init__(self, http: httpx.AsyncClient, api_key: str):
        self._http = http
        self._api_key = api_key

    async def imdb_rating(self, imdb_id: str) -> tuple[str | None, int | None]:
        try:
            response = await self._http.get(OMDB_API, params={"i": imdb_id, "apikey": self._api_key})
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as error:
            log.warning("OMDb request for %s failed: %s", imdb_id, error)
            return None, None
        if data.get("Response") != "True":
            log.warning("OMDb has no data for %s: %s", imdb_id, data.get("Error"))
            return None, None
        rating = data.get("imdbRating")
        votes = (data.get("imdbVotes") or "").replace(",", "")
        return (rating if rating and rating != "N/A" else None), (int(votes) if votes.isdigit() else None)


class WikidataClient:
    """Maps Google's knowledge-graph ids (the `kgmid` in Google links) to IMDb ids."""

    def __init__(self, http: httpx.AsyncClient):
        self._http = http

    async def imdb_id_for_google_id(self, kgmid: str) -> str | None:
        if not KGMID_RE.match(kgmid):
            return None
        # Old ids (/m/…) are Freebase ids (P646), newer ones (/g/…) Google Knowledge Graph ids (P2671).
        query = (
            f'SELECT ?imdb WHERE {{ ?item wdt:P646|wdt:P2671 "{kgmid}"; wdt:P345 ?imdb. '
            f'FILTER(STRSTARTS(?imdb, "tt")) }} LIMIT 1'
        )
        try:
            response = await self._http.get(
                WIKIDATA_SPARQL,
                params={"query": query, "format": "json"},
                headers={"User-Agent": WIKIDATA_USER_AGENT, "Accept": "application/sparql-results+json"},
            )
            response.raise_for_status()
            bindings = response.json()["results"]["bindings"]
        except (httpx.HTTPError, ValueError, KeyError) as error:
            log.warning("Wikidata lookup for %s failed: %s", kgmid, error)
            return None
        return bindings[0]["imdb"]["value"] if bindings else None


class MovieFinder:
    def __init__(self, http: httpx.AsyncClient, tmdb: TmdbClient, omdb: OmdbClient | None, max_results: int):
        self._http = http
        self._tmdb = tmdb
        self._omdb = omdb
        self._wikidata = WikidataClient(http)
        self._max_results = max_results

    async def find(self, lookup: Lookup) -> list[Movie]:
        movies = []
        for media_type, tmdb_id in await self._targets(lookup):
            movie = await self._tmdb.details(media_type, tmdb_id)
            if self._omdb and movie.imdb_id:
                rating, votes = await self._omdb.imdb_rating(movie.imdb_id)
                movie = replace(movie, imdb_rating=rating, imdb_votes=votes)
            movies.append(movie)
        return movies

    async def _targets(self, lookup: Lookup) -> list[tuple[str, int]]:
        if isinstance(lookup, UnknownLink):
            lookup = await self._resolve_link(lookup.url)
        match lookup:
            case SearchQuery(text, kgmid):
                # The title Google shows isn't always one TMDB knows ("Мішель Дарнелл" is "The Boss"), Google's id is exact.
                candidate = await self._by_google_id(kgmid) if kgmid else None
                candidates = [candidate] if candidate else await self._search(text)
            case ImdbRef(imdb_id):
                candidate = await self._tmdb.find_by_imdb_id(imdb_id)
                candidates = [candidate] if candidate else []
            case TmdbRef(media_type, tmdb_id):
                return [(media_type, tmdb_id)]
            case _:
                return []
        return [(c.media_type, c.tmdb_id) for c in candidates]

    async def _by_google_id(self, kgmid: str) -> Candidate | None:
        imdb_id = await self._wikidata.imdb_id_for_google_id(kgmid)
        candidate = await self._tmdb.find_by_imdb_id(imdb_id) if imdb_id else None
        log.debug("Google id %s -> IMDb %s -> %s", kgmid, imdb_id, candidate)
        return candidate

    async def _search(self, text: str) -> list[Candidate]:
        fallback: list[Candidate] = []
        for variant in search_variants(text):
            candidates = await self._tmdb.search(variant.title, variant.year)
            if variant.year:
                candidates = closest_to_year(candidates, variant.year)
            matches, exact = pick_matches(candidates, variant.title, self._max_results)
            log.debug("Search %r (%s): %d matches, exact=%s", variant.title, variant.year, len(matches), exact)
            if exact:
                return matches
            fallback = fallback or matches
        return fallback

    async def _resolve_link(self, url: str) -> Lookup | None:
        """Follows short links (g.co/kgs/…, share.google/…) until they point at Google search, IMDb or TMDB."""
        for _ in range(MAX_REDIRECTS):
            try:
                async with self._http.stream("GET", url) as response:
                    location = response.headers.get("location") if response.is_redirect else None
            except httpx.HTTPError as error:
                log.warning("Could not open %s: %s", url, error)
                return None
            if not location:
                log.info("Unsupported link: %s", url)
                return None
            url = urljoin(url, location)
            lookup = parse_url(url)
            if lookup is None or not isinstance(lookup, UnknownLink):
                return lookup
        return None


def _translation(translations: list[dict], language: str, field: str) -> str:
    """`field` of the TMDB translation into `language` ("uk-UA"), preferring the same country; "" if there's none."""
    code, _, country = language.partition("-")
    matching = sorted((t for t in translations if t.get("iso_639_1") == code), key=lambda t: t.get("iso_3166_1") != country)
    return next((value for t in matching if (value := (t.get("data") or {}).get(field))), "")


def _year(date_string: str | None) -> int | None:
    return int(date_string[:4]) if date_string and date_string[:4].isdigit() else None
