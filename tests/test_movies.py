import asyncio

import httpx

from moviebot.movies import Candidate, MovieFinder, OmdbClient, TmdbClient, pick_matches
from moviebot.parsing import parse_message


def movie(tmdb_id, title, year, votes, popularity, original_title=None):
    return {
        "id": tmdb_id, "media_type": "movie", "title": title, "original_title": original_title or title,
        "release_date": f"{year}-06-01", "vote_count": votes, "popularity": popularity,
    }


def tv(tmdb_id, name, year, votes, popularity):
    return {
        "id": tmdb_id, "media_type": "tv", "name": name, "original_name": name,
        "first_air_date": f"{year}-01-01", "vote_count": votes, "popularity": popularity,
    }


DUNE_2021 = movie(438631, "Dune", 2021, 12000, 100)
DUNE_1984 = movie(841, "Dune", 1984, 3000, 40)
DUNE_PART_TWO = movie(693134, "Dune: Part Two", 2024, 7000, 150)
DUNE_SHORT = movie(999001, "Dune", 2015, 2, 0.5)
INCEPTION = movie(27205, "Inception", 2010, 36000, 80)
GODFATHER = movie(238, "The Godfather", 1972, 20000, 90)
GODFATHER_1991 = movie(70000, "Godfather", 1991, 100, 3)
FARGO_MOVIE = movie(275, "Fargo", 1996, 6000, 30)
FARGO_TV = tv(60622, "Fargo", 2014, 3000, 60)

SEARCH = {
    "dune": [DUNE_PART_TWO, DUNE_2021, DUNE_1984, tv(1, "Frank Herbert's Dune", 2000, 300, 10), DUNE_SHORT,
             {"id": 5, "media_type": "person", "name": "Dune Person"}],
    "inception": [INCEPTION],
    "godfather": [GODFATHER, GODFATHER_1991],
    "fargo": [FARGO_MOVIE, FARGO_TV],
}

DETAILS = {
    ("movie", 438631): {"title": "Dune", "original_title": "Dune", "release_date": "2021-09-15", "imdb_id": "tt1160419",
                        "overview": "Paul Atreides...", "genres": [{"name": "Science Fiction"}], "runtime": 155,
                        "poster_path": "/dune.jpg", "vote_average": 7.8, "vote_count": 12000},
    ("movie", 841): {"title": "Dune", "original_title": "Dune", "release_date": "1984-12-14", "imdb_id": "tt0087182",
                     "overview": "In the year 10,191...", "genres": [], "runtime": 137},
    ("movie", 27205): {"title": "Inception", "original_title": "Inception", "release_date": "2010-07-15",
                       "imdb_id": "tt1375666", "overview": "Cobb, a skilled thief...", "genres": [{"name": "Action"}],
                       "runtime": 148, "poster_path": "/inception.jpg"},
    ("movie", 238): {"title": "The Godfather", "release_date": "1972-03-14", "imdb_id": "tt0068646", "overview": "Spanning..."},
    ("movie", 70000): {"title": "Godfather", "release_date": "1991-01-01", "imdb_id": None, "overview": "",
                       "vote_average": 7.1, "vote_count": 100},
    ("movie", 275): {"title": "Fargo", "release_date": "1996-03-08", "imdb_id": "tt0116282", "overview": "Jerry..."},
    ("tv", 60622): {"name": "Fargo", "first_air_date": "2014-04-15", "external_ids": {"imdb_id": "tt2802850"},
                    "overview": "A close-knit anthology...", "number_of_seasons": 5, "episode_run_time": [60]},
}

OMDB = {"tt1160419": ("8.0", "1,012,345"), "tt1375666": ("8.8", "2,612,000")}


def fake_api(request: httpx.Request) -> httpx.Response:
    params = request.url.params
    path = request.url.path
    if request.url.host == "g.co":
        return httpx.Response(302, headers={"location": "https://www.google.com/search?kgmid=/m/0661ql3&q=Inception"})
    if request.url.host == "www.omdbapi.com":
        if params["i"] not in OMDB:
            return httpx.Response(200, json={"Response": "False", "Error": "Incorrect IMDb ID."})
        rating, votes = OMDB[params["i"]]
        return httpx.Response(200, json={"Response": "True", "imdbRating": rating, "imdbVotes": votes})

    assert request.url.host == "api.themoviedb.org"
    assert params["api_key"] == "tmdb-key"
    if path == "/3/search/multi":
        return httpx.Response(200, json={"results": SEARCH.get(params["query"].lower(), [])})
    if path in ("/3/search/movie", "/3/search/tv"):
        media_type = path.rsplit("/", 1)[1]
        year = int(params.get("year") or params.get("first_air_date_year"))
        results = [r for r in SEARCH.get(params["query"].lower(), [])
                   if r["media_type"] == media_type and (r.get("release_date") or r.get("first_air_date")).startswith(str(year))]
        return httpx.Response(200, json={"results": results})
    if path.startswith("/3/find/"):
        return httpx.Response(200, json={"movie_results": [INCEPTION] if path.endswith("tt1375666") else [], "tv_results": []})
    _, _, media_type, tmdb_id = path.split("/")
    data = dict(DETAILS[(media_type, int(tmdb_id))])
    if not data.get("overview") and params["language"] == "en-US":
        data["overview"] = "English fallback overview"
    return httpx.Response(200, json=data)


def find(text, language="en-US", omdb=True, include_tv=True):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake_api)) as http:
            finder = MovieFinder(
                http,
                TmdbClient(http, "tmdb-key", language, include_tv),
                OmdbClient(http, "omdb-key") if omdb else None,
                max_results=3,
            )
            results = []
            for lookup in parse_message(text):
                results.extend(await finder.find(lookup))
            return results

    return asyncio.run(run())


def titles(movies):
    return [(m.title, m.year) for m in movies]


def test_ambiguous_title_posts_every_plausible_movie():
    assert titles(find("Dune")) == [("Dune", 2021), ("Dune", 1984)]


def test_year_picks_one():
    assert titles(find("Dune (2021)")) == [("Dune", 2021)]


def test_movie_and_series_with_the_same_name():
    movies = find("Fargo")
    assert [(m.media_type, m.title) for m in movies] == [("tv", "Fargo"), ("movie", "Fargo")]
    assert movies[0].seasons == 5 and movies[0].imdb_id == "tt2802850"
    assert [m.media_type for m in find("Fargo", include_tv=False)] == ["movie"]


def test_famous_movie_is_posted_next_to_an_obscure_exact_match():
    assert titles(find("Godfather")) == [("The Godfather", 1972), ("Godfather", 1991)]


def test_google_link_with_extra_words():
    assert titles(find("https://www.google.com/search?q=inception+2010+film")) == [("Inception", 2010)]


def test_short_google_link_is_followed():
    assert titles(find("https://g.co/kgs/AbC123")) == [("Inception", 2010)]


def test_imdb_link():
    assert titles(find("https://www.imdb.com/title/tt1375666/")) == [("Inception", 2010)]


def test_details_and_imdb_rating():
    [inception] = find("Inception")
    assert inception.imdb_rating == "8.8"
    assert inception.imdb_votes == 2_612_000
    assert inception.runtime_minutes == 148
    assert inception.genres == ("Action",)
    assert inception.poster_url == "https://image.tmdb.org/t/p/w780/inception.jpg"


def test_without_omdb_key_there_is_no_imdb_rating():
    [inception] = find("Inception", omdb=False)
    assert inception.imdb_rating is None


def test_missing_translation_falls_back_to_english_overview():
    movies = find("Godfather", language="uk-UA")
    assert movies[1].overview == "English fallback overview"


def test_not_found():
    assert find("Some movie that does not exist") == []


def test_pick_matches_without_exact_match_trusts_tmdb_order():
    candidates = [Candidate("movie", 1, "The Matrix", "The Matrix", 1999, 25000, 70),
                  Candidate("movie", 2, "The Matrix Reloaded", "The Matrix Reloaded", 2003, 10000, 40)]
    assert pick_matches(candidates, "Matrix", 3) == ([candidates[0]], False)
