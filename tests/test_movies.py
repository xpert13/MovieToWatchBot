import asyncio

import httpx

from moviebot.movies import Candidate, MovieFinder, OmdbClient, TmdbClient, Translator, pick_matches
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


def translations(*items):
    return {"translations": [{"iso_639_1": lang, "iso_3166_1": country, "data": {"title": title, "overview": overview}}
                             for lang, country, title, overview in items]}


DUNE_2021 = movie(438631, "Dune", 2021, 12000, 100)
DUNE_1984 = movie(841, "Dune", 1984, 3000, 40)
DUNE_PART_TWO = movie(693134, "Dune: Part Two", 2024, 7000, 150)
DUNE_SHORT = movie(999001, "Dune", 2015, 2, 0.5)
INCEPTION = movie(27205, "Inception", 2010, 36000, 80)
GODFATHER = movie(238, "The Godfather", 1972, 20000, 90)
GODFATHER_1991 = movie(70000, "Godfather", 1991, 100, 3)
FARGO_MOVIE = movie(275, "Fargo", 1996, 6000, 30)
FARGO_TV = tv(60622, "Fargo", 2014, 3000, 60)
# How TMDB returns Parasite (2019) when searching in Ukrainian and in English.
PARASITE_UK = movie(496243, "Паразити", 2019, 19000, 60, original_title="기생충")
PARASITE_EN = {**PARASITE_UK, "title": "Parasite"}
PARASITE_1982 = movie(27000, "Parasite", 1982, 150, 2)
# TMDB knows it as "Ride or Die" / "Бойові подруги", not as "Їдь або помри".
RIDE_OR_DIE = tv(241882, "Ride or Die", 2026, 115, 40)
# TMDB stores "'" and finds nothing when searched with the Ukrainian "ʼ".
WILD_HORSE_NINE = movie(891621, "Дикий кінь номер дев'ять", 2026, 40, 20, original_title="Wild Horse Nine")
THE_BOSS = movie(323676, "Леді Бос", 2016, 1500, 15, original_title="The Boss")

SEARCH = {
    "dune": [DUNE_PART_TWO, DUNE_2021, DUNE_1984, tv(1, "Frank Herbert's Dune", 2000, 300, 10), DUNE_SHORT,
             {"id": 5, "media_type": "person", "name": "Dune Person"}],
    "inception": [INCEPTION],
    "godfather": [GODFATHER, GODFATHER_1991, tv(70001, "Godfather", 2021, 30, 2)],
    "fargo": [FARGO_MOVIE, FARGO_TV],
    "parasite": [PARASITE_1982, PARASITE_UK],
    "паразити": [PARASITE_UK],
    "дикий кінь номер дев'ять": [WILD_HORSE_NINE],
    "ride or die": [movie(573435, "Bad Boys: Ride or Die", 2024, 3500, 30), RIDE_OR_DIE],
    "something unknown": [movie(1, "Something Unknown Returns", 2020, 10, 1)],
}
# Searching in English returns English titles.
SEARCH_EN = {"parasite": [PARASITE_1982, PARASITE_EN], "паразити": [PARASITE_EN]}

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
                       "vote_average": 7.1, "vote_count": 100,
                       "translations": translations(("en", "US", "", "English fallback overview"))},
    # Real TMDB data (requested in uk-UA): no Ukrainian translation, so TMDB gives the Chinese original title.
    ("movie", 1241486): {"title": "解密", "original_title": "解密", "release_date": "2024-09-30", "overview": "",
                         "translations": translations(("zh", "CN", "解密", "1940年代…"), ("en", "US", "Decoded", "In the 1940s…"))},
    ("movie", 496243): {"title": "Паразити", "original_title": "기생충", "release_date": "2019-05-30", "overview": "У сім’ї…",
                        "translations": translations(("en", "US", "Parasite", "All unemployed…"), ("uk", "UA", "Паразити", "У сім’ї…"))},
    # Originally English: TMDB leaves the English translation's title empty.
    ("movie", 438632): {"title": "Dune", "original_title": "Dune", "release_date": "2021-09-15", "overview": "Paul…",
                        "translations": translations(("en", "US", "", "Paul…"))},
    ("movie", 275): {"title": "Fargo", "release_date": "1996-03-08", "imdb_id": "tt0116282", "overview": "Jerry..."},
    ("movie", 323676): {"title": "Леді Бос", "original_title": "The Boss", "release_date": "2016-03-28",
                        "imdb_id": "tt2702724", "overview": "..."},
    ("movie", 891621): {"title": "Дикий кінь номер дев'ять", "original_title": "Wild Horse Nine",
                        "release_date": "2026-11-06", "overview": "..."},
    ("tv", 241882): {"name": "Бойові подруги", "original_name": "Ride or Die", "first_air_date": "2026-07-15",
                     "overview": "Best friends Debbie and Judith..."},
    ("tv", 60622): {"name": "Fargo", "first_air_date": "2014-04-15", "external_ids": {"imdb_id": "tt2802850"},
                    "overview": "A close-knit anthology...", "number_of_seasons": 5, "episode_run_time": [60]},
}

# TMDB's year filter also returns movies re-released that year.
RERELEASES = {(841, 2021)}

FIND = {"tt1375666": INCEPTION, "tt2702724": THE_BOSS}
# Google knowledge-graph id -> IMDb id, as Wikidata knows it.
WIKIDATA = {"/m/01312b52": "tt2702724"}
# MyMemory, Ukrainian -> English.
TRANSLATIONS = {"Їдь або помри": "Ride or die", "Щось невідоме": "Something unknown"}

OMDB = {"tt1160419": ("8.0", "1,012,345"), "tt1375666": ("8.8", "2,612,000")}


def fake_api(request: httpx.Request) -> httpx.Response:
    params = request.url.params
    path = request.url.path
    if request.url.host == "g.co":
        return httpx.Response(302, headers={"location": "https://www.google.com/search?kgmid=/m/0661ql3&q=Inception"})
    # The real chain of a link shared from the Google app.
    if request.url.host == "share.google":
        return httpx.Response(302, headers={"location": "https://www.google.com/share.google?q=oKoxXQxkRbryUwWeU"})
    if request.url.host == "www.google.com" and path == "/share.google":
        return httpx.Response(301, headers={"location": (
            "https://www.google.com/search?kgmid=/m/01312b52&hl=uk-UA&q=%D0%9C%D1%96%D1%88%D0%B5%D0%BB%D1%8C+"
            "%D0%94%D0%B0%D1%80%D0%BD%D0%B5%D0%BB%D0%BB&shem=dlvs1,epsd1,rimspwouoe&shndl=17&source=sh/x/kp/osrp/m5/3")})
    if request.url.host == "api.mymemory.translated.net":
        assert params["langpair"] == "uk|en"
        if params["q"] == "Ліміт":
            return httpx.Response(200, json={"responseStatus": 429, "quotaFinished": True, "responseData": {
                "translatedText": "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY."}})
        return httpx.Response(200, json={"responseStatus": 200, "responseData": {"translatedText": TRANSLATIONS.get(params["q"], params["q"])}})
    if request.url.host == "query.wikidata.org":
        kgmid = params["query"].split('"')[1]
        if kgmid == "/m/broken":
            return httpx.Response(503)
        bindings = [{"imdb": {"type": "literal", "value": WIKIDATA[kgmid]}}] if kgmid in WIKIDATA else []
        return httpx.Response(200, json={"results": {"bindings": bindings}})
    if request.url.host == "www.omdbapi.com":
        if params["i"] not in OMDB:
            return httpx.Response(200, json={"Response": "False", "Error": "Incorrect IMDb ID."})
        rating, votes = OMDB[params["i"]]
        return httpx.Response(200, json={"Response": "True", "imdbRating": rating, "imdbVotes": votes})

    assert request.url.host == "api.themoviedb.org"
    assert params["api_key"] == "tmdb-key"
    search = {**SEARCH, **SEARCH_EN} if params["language"] == "en-US" else SEARCH
    if path == "/3/search/multi":
        return httpx.Response(200, json={"results": search.get(params["query"].lower(), [])})
    if path in ("/3/search/movie", "/3/search/tv"):
        media_type = path.rsplit("/", 1)[1]
        year = int(params.get("year") or params.get("first_air_date_year"))
        results = [r for r in search.get(params["query"].lower(), [])
                   if r["media_type"] == media_type
                   and ((r.get("release_date") or r.get("first_air_date")).startswith(str(year)) or (r["id"], year) in RERELEASES)]
        return httpx.Response(200, json={"results": results})
    if path.startswith("/3/find/"):
        found = FIND.get(path.rsplit("/", 1)[1])
        return httpx.Response(200, json={"movie_results": [found] if found else [], "tv_results": []})
    _, _, media_type, tmdb_id = path.split("/")
    assert "translations" in params["append_to_response"]
    return httpx.Response(200, json=DETAILS[(media_type, int(tmdb_id))])


def find(text, language="en-US", omdb=True, include_tv=True):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake_api)) as http:
            finder = MovieFinder(
                http,
                TmdbClient(http, "tmdb-key", language, include_tv),
                OmdbClient(http, "omdb-key") if omdb else None,
                max_results=3,
                translator=None if language.startswith("en") else Translator(http, language),
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


def test_year_picks_one_even_if_the_other_was_rereleased_that_year():
    assert titles(find("Dune (2021)")) == [("Dune", 2021)]


def test_movie_and_series_with_the_same_name():
    movies = find("Fargo")
    assert [(m.media_type, m.title) for m in movies] == [("tv", "Fargo"), ("movie", "Fargo")]
    assert movies[0].seasons == 5 and movies[0].imdb_id == "tt2802850"
    assert [m.media_type for m in find("Fargo", include_tv=False)] == ["movie"]


def test_famous_movie_is_posted_next_to_the_best_obscure_exact_match():
    assert titles(find("Godfather")) == [("The Godfather", 1972), ("Godfather", 1991)]


def test_google_link_with_extra_words():
    assert titles(find("https://www.google.com/search?q=inception+2010+film")) == [("Inception", 2010)]


def test_short_google_link_is_followed():
    assert titles(find("https://g.co/kgs/AbC123")) == [("Inception", 2010)]


def test_google_app_share_link_uses_googles_movie_id():
    # Google calls it "Мішель Дарнелл" - a title TMDB doesn't know - but its id leads to the exact movie.
    assert [(m.title, m.original_title, m.year) for m in find("https://share.google/oKoxXQxkRbryUwWeU")] == [
        ("Леді Бос", "The Boss", 2016)
    ]


def test_google_link_falls_back_to_the_title_when_its_id_is_unknown_or_wikidata_is_down():
    assert titles(find("https://www.google.com/search?q=Inception&kgmid=/g/11unknown")) == [("Inception", 2010)]
    assert titles(find("https://www.google.com/search?q=Inception&kgmid=/m/broken")) == [("Inception", 2010)]


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


def test_untranslated_title_falls_back_to_english_not_the_original_chinese_or_korean():
    [decoded] = find("https://www.themoviedb.org/movie/1241486", language="uk-UA")
    assert (decoded.title, decoded.original_title, decoded.overview) == ("Decoded", "解密", "In the 1940s…")
    [parasite] = find("https://www.themoviedb.org/movie/496243", language="uk-UA")
    assert (parasite.title, parasite.original_title) == ("Паразити", "기생충")
    [dune] = find("https://www.themoviedb.org/movie/438632", language="uk-UA")
    assert dune.title == "Dune"


def test_english_or_ukrainian_title_of_a_foreign_movie():
    # Only the English search knows it as "Parasite"; otherwise only the obscure 1982 film matches literally.
    assert titles(find("Parasite", language="uk-UA")) == [("Паразити", 2019)]
    assert titles(find("Паразити", language="uk-UA")) == [("Паразити", 2019)]


def test_local_title_tmdb_does_not_know_is_found_by_its_english_translation():
    for text in ("Їдь або помри (2026)", "Їдь або помри"):
        # Without the year, the much more popular "Bad Boys: Ride or Die" must not sneak in - it isn't an exact title.
        assert [(m.title, m.original_title, m.year) for m in find(text, language="uk-UA")] == [
            ("Бойові подруги", "Ride or Die", 2026)
        ]


def test_translation_is_only_trusted_for_an_exact_title():
    # "Something unknown" only loosely matches "Something Unknown Returns" - better nothing than a random movie.
    assert find("Щось невідоме", language="uk-UA") == []
    assert find("Ліміт", language="uk-UA") == []


def test_ukrainian_apostrophe():
    assert titles(find("Дикий кінь номер девʼять", language="uk-UA")) == [("Дикий кінь номер дев'ять", 2026)]


def test_not_found():
    assert find("Some movie that does not exist") == []


def test_pick_matches_without_exact_match_trusts_tmdb_order():
    candidates = [Candidate("movie", 1, "The Matrix", "The Matrix", 1999, 25000, 70),
                  Candidate("movie", 2, "The Matrix Reloaded", "The Matrix Reloaded", 2003, 10000, 40)]
    assert pick_matches(candidates, "Matrix", 3) == ([candidates[0]], False)
