from moviebot.formatting import format_movie, format_runtime, format_votes, visible_length
from moviebot.movies import Movie


def make_movie(**overrides):
    fields = dict(
        media_type="movie", tmdb_id=27205, title="Inception", original_title="Inception", year=2010,
        overview="Cobb, a skilled thief who commits corporate espionage <by> infiltrating dreams & more.",
        genres=("Action", "Science Fiction"), runtime_minutes=148, seasons=None,
        poster_url=None, imdb_id="tt1375666", tmdb_rating=8.4, tmdb_votes=36000,
        imdb_rating="8.8", imdb_votes=2_612_000,
    )
    return Movie(**{**fields, **overrides})


def test_caption():
    assert format_movie(make_movie(), 1024) == (
        "🎬 <b>Inception</b> (2010)\n"
        "⭐ IMDb <b>8.8</b>/10 (2.6M votes)\n"
        "🎭 Action, Science Fiction · ⏱ 2h 28m\n"
        "\n"
        "Cobb, a skilled thief who commits corporate espionage &lt;by&gt; infiltrating dreams &amp; more.\n"
        "\n"
        '🔗 <a href="https://www.imdb.com/title/tt1375666/">IMDb</a> · <a href="https://www.themoviedb.org/movie/27205">TMDB</a>'
    )


def test_series_with_original_title_and_tmdb_rating():
    caption = format_movie(make_movie(
        media_type="tv", tmdb_id=1, title="Темні", original_title="Dark", year=2017, seasons=3,
        runtime_minutes=None, genres=("Drama",), imdb_rating=None, imdb_id=None, tmdb_votes=6789,
    ), 1024)
    assert caption.startswith("📺 <b>Темні</b> (2017)\n<i>Dark</i>\n⭐ TMDB <b>8.4</b>/10 (7K votes)\n🎭 TV series, 3 seasons · Drama\n")
    assert caption.endswith('🔗 <a href="https://www.themoviedb.org/tv/1">TMDB</a>')


def test_long_overview_is_shortened_to_telegram_caption_limit():
    caption = format_movie(make_movie(overview="word " * 400), 1024)
    assert visible_length(caption) <= 1024
    assert "word…" in caption
    assert caption.endswith("TMDB</a>")


def test_numbers():
    assert format_votes(2_612_000) == "2.6M"
    assert format_votes(1_000_000) == "1M"
    assert format_votes(45_400) == "45K"
    assert format_votes(999) == "999"
    assert format_runtime(148) == "2h 28m"
    assert format_runtime(120) == "2h"
    assert format_runtime(45) == "45m"
