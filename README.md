# Movies To Watch – Telegram bot

Post a movie name (or a Google search / IMDb / TMDB link) in your channel and the bot answers with a card:
poster, title, year, IMDb rating, genres, runtime and description.

- `Dune` → two cards, *Dune (2021)* and *Dune (1984)*. Delete the one you didn't mean.
- `Dune 2021` or `Dune (2021)` → just the 2021 one.
- `https://www.google.com/search?q=dune+2021+film`, `https://g.co/kgs/…`, `https://share.google/…` (shared from the Google app),
  `https://www.imdb.com/title/tt1160419/`, `https://www.themoviedb.org/movie/438631` all work.
  Short Google links are followed to the search page. When Google's link names the exact movie (its `kgmid`), the bot
  uses that – Google's titles aren't always the ones TMDB knows (it calls *The Boss* "Мішель Дарнелл") – otherwise it
  searches for the text in the query.
- Several lines in one message → one card per line.
- Ukrainian, English or original titles all work. If TMDB doesn't know a local title at all (`Їдь або помри` is
  *Ride or Die*), the bot translates it to English and accepts the result only if a title matches exactly.
- Nothing found → the bot replies "Couldn't find a movie for: …".

Movie data comes from [TMDB](https://www.themoviedb.org) (search, posters, descriptions, works with Ukrainian/Russian titles too),
the IMDb rating from [OMDb](https://www.omdbapi.com). Without a key: Google's movie ids are matched to IMDb ids with
[Wikidata](https://www.wikidata.org), and titles are translated with [MyMemory](https://mymemory.translated.net)
(free up to 5,000 characters a day, used only when nothing else was found).

## 1. Get the keys

1. **Telegram bot** – in Telegram open [@BotFather](https://t.me/BotFather), send `/newbot`, copy the token.
2. **TMDB** – create a free account, then go to *Settings → API* (<https://www.themoviedb.org/settings/api>) and request
   an API key (personal use). Either the *API Key* or the *API Read Access Token* works.
3. **OMDb** (for the IMDb rating) – <https://www.omdbapi.com/apikey.aspx>, choose *FREE*, click the activation link in the email.
   Optional: without it the card shows the TMDB rating instead.

## 2. Add the bot to your channel or group

Make the bot an **admin**:

- **Channel:** *Manage channel* → *Administrators* → *Add admin* → find your bot. It needs **Post messages**.
- **Group:** *Edit* → *Administrators* → *Add admin* → find your bot. Being a regular member is not enough: Telegram only
  delivers commands and replies to bots that aren't admins, so the bot would never see your messages.

Also give it **Delete messages** if you turn on `DELETE_ORIGINAL`.

The bot only sees messages posted after it was added. To get cards for movies already in the channel, post them again.

## 3. Run it on the Raspberry Pi (CasaOS)

To install it as a regular CasaOS app from Docker Hub instead, see [CASAOS.md](CASAOS.md).

Clone the repository on the Pi and start it with Docker Compose (CasaOS already has Docker):

```bash
# on the Pi (use "sudo docker …" if your user isn't in the docker group)
ssh <user>@<pi-address>
git clone https://github.com/xpert13/MovieToWatchBot.git ~/movies-to-watch-bot
cd ~/movies-to-watch-bot
cp .env.example .env
nano .env                       # paste TELEGRAM_BOT_TOKEN, TMDB_API_KEY, OMDB_API_KEY
docker compose up -d --build
docker compose logs -f          # should say "Bot started"
```

Post a movie name in the channel. The log shows the channel id, e.g. `Chat -1001234567890 ('Movies'): 1 lookup(s)…`.
Put it into `ALLOWED_CHAT_IDS` in `.env` so strangers who find the bot can't use it, then `docker compose up -d` to apply.
You can also send a movie name to the bot in a private chat to test it.

The container restarts automatically after a reboot or crash. To update to the latest code:

```bash
cd ~/movies-to-watch-bot && git pull && docker compose up -d --build
```

## Settings (`.env`)

| Variable | Default | |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | – | required |
| `TMDB_API_KEY` | – | required |
| `OMDB_API_KEY` | empty | IMDb rating; without it the TMDB rating is shown |
| `ALLOWED_CHAT_IDS` | empty (any chat) | comma-separated chat ids the bot reacts in |
| `LANGUAGE` | `en-US` | language of titles/descriptions, e.g. `uk-UA` (falls back to English if there's no translation) |
| `MAX_RESULTS` | `3` | max cards when several movies share a name |
| `INCLUDE_TV` | `true` | also find TV series |
| `DELETE_ORIGINAL` | `false` | delete your message after the card is posted (kept if nothing was found) |
| `LOG_LEVEL` | `INFO` | `DEBUG` shows every search attempt |

## Development

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
set -a && . ./.env && set +a && .venv/bin/python -m moviebot   # run locally
```

Stop the Pi container while running locally – Telegram allows only one bot instance to poll at a time.
