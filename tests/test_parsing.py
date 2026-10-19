from datetime import date

from moviebot.parsing import (
    ImdbRef,
    SearchQuery,
    SearchVariant,
    TmdbRef,
    UnknownLink,
    normalize_title,
    parse_message,
    parse_url,
    search_variants,
    split_year,
)

TODAY = date(2026, 10, 19)


def test_plain_title():
    assert parse_message("  Dune  ") == [SearchQuery("Dune")]


def test_each_line_is_a_movie_and_duplicates_are_dropped():
    assert parse_message("Dune\n\nInception\nDune") == [SearchQuery("Dune"), SearchQuery("Inception")]


def test_commands_are_ignored():
    assert parse_message("/start") == []


def test_google_search_link():
    url = "https://www.google.com/search?q=dune+2021+film&oq=dune&sourceid=chrome&ie=UTF-8"
    assert parse_message(url) == [SearchQuery("dune 2021 film")]
    shared = "https://www.google.com/search?kgmid=/m/01312b52&hl=uk-UA&q=%D0%9C%D1%96%D1%88%D0%B5%D0%BB%D1%8C+%D0%94%D0%B0%D1%80%D0%BD%D0%B5%D0%BB%D0%BB"
    assert parse_message(shared) == [SearchQuery("Мішель Дарнелл", kgmid="/m/01312b52")]


def test_google_link_with_text_around_it_and_country_domain():
    text = "watch this: https://www.google.com.ua/search?q=%D0%B4%D1%8E%D0%BD%D0%B0 !"
    assert parse_message(text) == [SearchQuery("дюна")]


def test_google_consent_and_redirect_wrappers():
    consent = "https://consent.google.com/ml?continue=https://www.google.com/search?q%3DInception%26hl%3Den&gl=DE"
    assert parse_url(consent) == SearchQuery("Inception")
    assert parse_url("https://www.google.com/url?q=https://www.imdb.com/title/tt1375666/&sa=U") == ImdbRef("tt1375666")


def test_imdb_and_tmdb_links():
    assert parse_url("https://m.imdb.com/title/tt1375666/?ref_=nv_sr_srsg_0") == ImdbRef("tt1375666")
    assert parse_url("https://www.themoviedb.org/movie/27205-inception") == TmdbRef("movie", 27205)
    assert parse_url("https://www.themoviedb.org/tv/1399-game-of-thrones?language=uk") == TmdbRef("tv", 1399)
    assert parse_url("https://www.imdb.com/chart/top/") is None


def test_short_links_are_followed_later():
    assert parse_message("https://g.co/kgs/AbC123") == [UnknownLink("https://g.co/kgs/AbC123")]
    assert parse_message("https://share.google/xYz") == [UnknownLink("https://share.google/xYz")]
    # The share code in "q" is not a movie title - keep following until the real search page.
    share_page = "https://www.google.com/share.google?q=oKoxXQxkRbryUwWeU"
    assert parse_url(share_page) == UnknownLink(share_page)


def test_split_year():
    assert split_year("Inception (2010)", TODAY) == ("Inception", 2010)
    assert split_year("Dune 2021 film", TODAY) == ("Dune film", 2021)
    assert split_year("1917", TODAY) == ("1917", None)
    assert split_year("2001: A Space Odyssey", TODAY) == ("2001: A Space Odyssey", None)
    assert split_year("Blade Runner 2049", TODAY) == ("Blade Runner 2049", None)


def test_search_variants_try_literal_title_before_dropping_words():
    assert search_variants("Scary Movie", TODAY) == [SearchVariant("Scary Movie"), SearchVariant("Scary")]
    assert search_variants("dune 2021 film", TODAY) == [
        SearchVariant("dune film", 2021),
        SearchVariant("dune 2021 film"),
        SearchVariant("dune", 2021),
    ]
    assert search_variants("Inception", TODAY) == [SearchVariant("Inception")]
    assert search_variants("фільм Дюна", TODAY) == [SearchVariant("фільм Дюна"), SearchVariant("Дюна")]


def test_normalize_title():
    assert normalize_title("Amélie") == normalize_title("amelie")
    assert normalize_title("Fast & Furious") == "fast and furious"
    assert normalize_title("Spider-Man: No Way Home") == "spider man no way home"
    assert normalize_title("Дюна") == normalize_title("дюна")
