"""Finds movies on TMDB (search, posters, descriptions) and their IMDb rating on OMDb."""

from __future__ import annotations

import asyncio
import logging
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
    exact = [c for c in candidates if wanted in (normalize_title(c.title), normalize_title(c.original_title))]
    if not exact:
        return [candidates[0]], False

    exact.sort(key=lambda c: (c.popularity, c.vote_count), reverse=True)
    max_votes = max(c.vote_count for c in exact)
    min_votes = max(MIN_VOTES, max_votes * VOTES_SHARE)
    min_popularity = exact[0].popularity * POPULARITY_SHARE
    picked = [exact[0]] + [c for c in exact[1:] if c.vote_count >= min_votes or c.popularity >= min_popularity]

    dominant = max(candidates[:5], key=lambda c: c.vote_count)
    if dominant not in exact and dominant.vote_count >= DOMINANT_FACTOR * max(max_votes, MIN_VOTES):
        picked.insert(0, dominant)
    return picked[:max_results], True


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
        if year is None:
            data = await self._get("/search/multi", query=title, include_adult="false")
            items = [(item, item.get("media_type")) for item in data.get("results", [])]
        else:
            requests = [self._get("/search/movie", query=title, year=year, include_adult="false")]
            if self._include_tv:
                requests.append(self._get("/search/tv", query=title, first_air_date_year=year, include_adult="false"))
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
        data = await self._get(f"/{media_type}/{tmdb_id}", append_to_response="external_ids")
        overview = data.get("overview") or ""
        if not overview and not self._language.startswith("en"):
            # Not every movie has a description in every language - English is the most complete.
            overview = (await self._get(f"/{media_type}/{tmdb_id}", language="en-US")).get("overview") or ""

        is_movie = media_type == "movie"
        runtime = data.get("runtime") if is_movie else next(iter(data.get("episode_run_time") or []), None)
        return Movie(
            media_type=media_type,
            tmdb_id=tmdb_id,
            title=data.get("title" if is_movie else "name") or "",
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


class MovieFinder:
    def __init__(self, http: httpx.AsyncClient, tmdb: TmdbClient, omdb: OmdbClient | None, max_results: int):
        self._http = http
        self._tmdb = tmdb
        self._omdb = omdb
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
            case SearchQuery(text):
                candidates = await self._search(text)
            case ImdbRef(imdb_id):
                candidate = await self._tmdb.find_by_imdb_id(imdb_id)
                candidates = [candidate] if candidate else []
            case TmdbRef(media_type, tmdb_id):
                return [(media_type, tmdb_id)]
            case _:
                return []
        return [(c.media_type, c.tmdb_id) for c in candidates]

    async def _search(self, text: str) -> list[Candidate]:
        fallback: list[Candidate] = []
        for variant in search_variants(text):
            matches, exact = pick_matches(await self._tmdb.search(variant.title, variant.year), variant.title, self._max_results)
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


def _year(date_string: str | None) -> int | None:
    return int(date_string[:4]) if date_string and date_string[:4].isdigit() else None
