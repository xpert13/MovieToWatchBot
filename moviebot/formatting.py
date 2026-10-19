"""Builds the Telegram message (HTML) for a movie card."""

from __future__ import annotations

import html
import re

from .movies import Movie

TAG_RE = re.compile(r"<[^>]+>")


def format_movie(movie: Movie, limit: int) -> str:
    """Caption with title, rating, genres, description and links, shortening the description to fit `limit`."""
    icon = "🎬" if movie.media_type == "movie" else "📺"
    year = f" ({movie.year})" if movie.year else ""
    head = [f"{icon} <b>{_e(movie.title)}</b>{year}"]
    if movie.original_title and movie.original_title != movie.title:
        head.append(f"<i>{_e(movie.original_title)}</i>")
    if rating := _rating_line(movie):
        head.append(rating)
    if facts := _facts_line(movie):
        head.append(facts)

    links = [f'<a href="{_e(movie.imdb_url)}">IMDb</a>'] if movie.imdb_url else []
    links.append(f'<a href="{_e(movie.tmdb_url)}">TMDB</a>')
    footer = "🔗 " + " · ".join(links)

    without_overview = "\n".join(head) + "\n\n" + footer
    budget = limit - visible_length(without_overview) - 2
    overview = _shorten(movie.overview, budget)
    if not overview:
        return without_overview
    return "\n".join(head) + "\n\n" + _e(overview) + "\n\n" + footer


def visible_length(html_text: str) -> int:
    """Length as Telegram counts it: text after parsing the HTML, in UTF-16 code units."""
    text = html.unescape(TAG_RE.sub("", html_text))
    return len(text.encode("utf-16-le")) // 2


def format_votes(votes: int) -> str:
    if votes >= 1_000_000:
        return f"{votes / 1_000_000:.1f}M".replace(".0M", "M")
    if votes >= 1_000:
        return f"{votes / 1_000:.0f}K"
    return str(votes)


def format_runtime(minutes: int) -> str:
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return f"{minutes}m"
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def _rating_line(movie: Movie) -> str | None:
    if movie.imdb_rating:
        votes = f" ({format_votes(movie.imdb_votes)} votes)" if movie.imdb_votes else ""
        return f"⭐ IMDb <b>{_e(movie.imdb_rating)}</b>/10{votes}"
    if movie.tmdb_rating:
        votes = f" ({format_votes(movie.tmdb_votes)} votes)" if movie.tmdb_votes else ""
        return f"⭐ TMDB <b>{movie.tmdb_rating:.1f}</b>/10{votes}"
    return None


def _facts_line(movie: Movie) -> str | None:
    facts = []
    if movie.media_type == "tv":
        facts.append("TV series" + (f", {movie.seasons} season{'s' if movie.seasons != 1 else ''}" if movie.seasons else ""))
    if movie.genres:
        facts.append(", ".join(movie.genres))
    if movie.runtime_minutes:
        facts.append(f"⏱ {format_runtime(movie.runtime_minutes)}")
    return "🎭 " + _e(" · ".join(facts)) if facts else None


def _shorten(text: str, budget: int) -> str:
    def length(s: str) -> int:
        return len(s.encode("utf-16-le")) // 2

    if length(text) <= budget:
        return text
    words = text.split()
    while words and length(" ".join(words) + "…") > budget:
        words.pop()
    return " ".join(words).rstrip(",;:-–—") + "…" if words else ""


def _e(text: str) -> str:
    return html.escape(text)
