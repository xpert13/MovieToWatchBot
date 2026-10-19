"""Telegram side: reads new posts in the channel and answers with movie cards."""

from __future__ import annotations

import html
import logging

import httpx
from telegram import InputFile, LinkPreviewOptions, Message, ReplyParameters, Update
from telegram.constants import MessageLimit, ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from .config import Config
from .formatting import format_movie
from .movies import Movie, MovieFinder, OmdbClient, TmdbClient, Translator
from .parsing import Lookup, parse_message

log = logging.getLogger(__name__)

HELP_TEXT = (
    "Send me a movie or series name (e.g. <i>Dune</i> or <i>Dune 2021</i>), "
    "or a Google search / IMDb / TMDB link, and I'll reply with its poster, description and IMDb rating.\n\n"
    "Add me as an admin to your channel and I'll do the same for every new post there."
)


class MovieBot:
    def __init__(self, config: Config):
        self.config = config
        self.http = httpx.AsyncClient(
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; MoviesToWatchBot/1.0)"},
        )
        tmdb = TmdbClient(self.http, config.tmdb_api_key, config.language, config.include_tv)
        omdb = OmdbClient(self.http, config.omdb_api_key) if config.omdb_api_key else None
        translator = None if config.language.startswith("en") else Translator(self.http, config.language)
        self.finder = MovieFinder(self.http, tmdb, omdb, config.max_results, translator)

    async def on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)

    async def on_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message, chat = update.effective_message, update.effective_chat
        if not message or not message.text:
            return
        if self.config.allowed_chat_ids and chat.id not in self.config.allowed_chat_ids:
            log.info("Ignoring chat %s (%r) - it's not in ALLOWED_CHAT_IDS", chat.id, chat.title or chat.username)
            return

        lookups = parse_message(message.text)
        log.info("Chat %s (%r): %d lookup(s) in %r", chat.id, chat.title or chat.username, len(lookups), message.text)
        everything_found = bool(lookups)
        for lookup in lookups:
            try:
                movies = await self.finder.find(lookup)
                if not movies:
                    log.info("Nothing found for %s", lookup)
                    await self._reply(message, f"🤷 Couldn't find a movie for: {_e(lookup.label)}")
                    everything_found = False
                for movie in movies:
                    log.info("Posting %s %s (%s)", movie.media_type, movie.title, movie.year)
                    await self._send_movie(message, movie)
            except Exception:
                log.exception("Lookup failed for %s", lookup)
                everything_found = False
                await self._reply(message, f"⚠️ Something went wrong while looking up: {_e(lookup.label)}")

        if self.config.delete_original and everything_found:
            try:
                await message.delete()
            except TelegramError as error:
                log.warning("Could not delete the original message (does the bot have 'Delete messages' permission?): %s", error)

    async def _send_movie(self, message: Message, movie: Movie) -> None:
        if movie.poster_url:
            try:
                poster = await self.http.get(movie.poster_url)
                poster.raise_for_status()
                await message.get_bot().send_photo(
                    chat_id=message.chat_id,
                    photo=InputFile(poster.content, filename="poster.jpg"),
                    caption=format_movie(movie, MessageLimit.CAPTION_LENGTH),
                    parse_mode=ParseMode.HTML,
                )
                return
            except (httpx.HTTPError, TelegramError) as error:
                log.warning("Could not send the poster for %s, sending text only: %s", movie.title, error)
        await message.get_bot().send_message(
            chat_id=message.chat_id,
            text=format_movie(movie, MessageLimit.MAX_TEXT_LENGTH),
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

    async def _reply(self, message: Message, text: str) -> None:
        await message.get_bot().send_message(
            chat_id=message.chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_parameters=ReplyParameters(message.message_id, allow_sending_without_reply=True),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

    async def close(self, _: Application) -> None:
        await self.http.aclose()


async def _log_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Error while handling an update", exc_info=context.error)


def _e(text: str) -> str:
    return html.escape(text)


def main() -> None:
    config = Config.from_env()
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=config.log_level)
    # httpx logs every request at INFO, including Telegram long-polling with the bot token in the URL.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    bot = MovieBot(config)
    app = Application.builder().token(config.telegram_token).post_shutdown(bot.close).build()
    app.add_handler(CommandHandler("start", bot.on_start, filters=filters.ChatType.PRIVATE))
    app.add_handler(MessageHandler(
        (filters.UpdateType.CHANNEL_POST | filters.UpdateType.MESSAGE) & filters.TEXT & ~filters.COMMAND,
        bot.on_post,
    ))
    app.add_error_handler(_log_error)

    log.info(
        "Bot started (language=%s, max results=%d, TV series=%s, IMDb ratings=%s, allowed chats=%s)",
        config.language, config.max_results, config.include_tv,
        "OMDb" if config.omdb_api_key else "off - TMDB rating used instead",
        ", ".join(map(str, sorted(config.allowed_chat_ids))) or "any",
    )
    app.run_polling(allowed_updates=[Update.MESSAGE, Update.CHANNEL_POST])


if __name__ == "__main__":
    main()
