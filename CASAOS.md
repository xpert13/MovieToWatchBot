# Publishing to Docker Hub and installing as a CasaOS app

You build the image on your Mac and push it to Docker Hub, then CasaOS downloads it from there like any other app.
The image is built for both **arm64** (Raspberry Pi 5) and **amd64** (regular PCs), so it runs on either.

The image contains no secrets: only `requirements.txt` and the `moviebot/` code are copied into it, and `.env` is also
excluded in `.dockerignore`. Your tokens are entered in CasaOS later, so a **public** Docker Hub repository is fine.

In the commands below replace `<dockerhub-user>` with your Docker Hub username.

## 1. One-time setup

### 1.1 Docker Hub repository

1. Sign up or log in at <https://hub.docker.com>.
2. *Create a repository* → name **`movie-to-watch-bot`** → visibility **Public** → *Create*.

### 1.2 Access token for pushing

1. Docker Hub → your avatar → *Account settings* → *Personal access tokens* → *Generate new token*.
2. Description `MacBook push`, access permissions **Read & Write** → *Generate*. Copy the token (it's shown only once).
3. Log in on the Mac and paste the token when asked for the password:

   ```bash
   docker login -u <dockerhub-user>
   ```

### 1.3 Builder that can build for several platforms

Docker Desktop's default builder can only build for one platform at a time. Create a second builder once:

```bash
docker buildx create --name multiarch --driver docker-container
docker buildx inspect multiarch --bootstrap   # starts it, the list of platforms must include linux/arm64 and linux/amd64
```

## 2. Build and publish the image

Run this from the project folder each time you want to publish a new version. Raise `VERSION` every time
(`1.0.0`, `1.0.1`, …) – CasaOS installs `latest`, the version tag lets you go back if a new version misbehaves.

```bash
cd ~/AlexProjects/MoviesToWatchTelegramBot
.venv/bin/pytest -q          # make sure the tests pass before publishing

VERSION=1.0.0
docker buildx build --builder multiarch \
  --platform linux/arm64,linux/amd64 \
  -t <dockerhub-user>/movie-to-watch-bot:$VERSION \
  -t <dockerhub-user>/movie-to-watch-bot:latest \
  --push .
```

The first build takes a few minutes (the amd64 half is emulated on the Mac), later ones are faster.
Check that both platforms got published:

```bash
docker buildx imagetools inspect <dockerhub-user>/movie-to-watch-bot:latest
# Platform: linux/arm64 and Platform: linux/amd64 must be in the output
```

## 3. Install the app in CasaOS

### 3.1 Stop any other copy of the bot first

Telegram lets only **one** copy of a bot read messages. If you started it before with `docker compose` from the
cloned repository on the Pi, stop and remove that one (your `.env` stays there, copy the values from it):

```bash
ssh <user>@<pi-address>
cd ~/movies-to-watch-bot && cat .env && docker compose down
```

Also stop it on the Mac if it runs there.

### 3.2 Import the app

1. Open the CasaOS dashboard → in the *Apps* section click **+** → **Install a customized app**.
2. Click **Import** (top right of the dialog), paste the YAML below, replace `<dockerhub-user>`, and confirm.
3. CasaOS fills in the form from it. Scroll to **Environment variables** and paste your values for
   `TELEGRAM_BOT_TOKEN`, `TMDB_API_KEY`, `OMDB_API_KEY` and `ALLOWED_CHAT_IDS` (the same as in your `.env`).
4. Click **Install**.

```yaml
name: movie-to-watch-bot

services:
  bot:
    image: <dockerhub-user>/movie-to-watch-bot:latest
    container_name: movie-to-watch-bot
    restart: unless-stopped
    environment:
      TELEGRAM_BOT_TOKEN: ""
      TMDB_API_KEY: ""
      OMDB_API_KEY: ""
      ALLOWED_CHAT_IDS: ""
      LANGUAGE: uk-UA
      MAX_RESULTS: "3"
      INCLUDE_TV: "true"
      DELETE_ORIGINAL: "false"
      LOG_LEVEL: INFO
    logging:
      driver: json-file
      options:
        max-size: 1m
        max-file: "3"
    x-casaos:
      envs:
        - container: TELEGRAM_BOT_TOKEN
          description:
            en_us: Bot token from @BotFather
        - container: TMDB_API_KEY
          description:
            en_us: TMDB API key or API Read Access Token
        - container: OMDB_API_KEY
          description:
            en_us: OMDb API key for IMDb ratings (optional)
        - container: ALLOWED_CHAT_IDS
          description:
            en_us: Comma-separated chat ids the bot reacts in, e.g. -1001234567890 (empty = any chat)
        - container: LANGUAGE
          description:
            en_us: Language of titles and descriptions, e.g. uk-UA or en-US
        - container: MAX_RESULTS
          description:
            en_us: Max cards when several movies share a name
        - container: INCLUDE_TV
          description:
            en_us: Also find TV series (true/false)
        - container: DELETE_ORIGINAL
          description:
            en_us: Delete the original message after posting the card (true/false)

x-casaos:
  architectures:
    - amd64
    - arm64
  main: bot
  author: Alex
  developer: Alex
  category: Utilities
  icon: https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/telegram.png
  title:
    en_us: Movies To Watch Bot
  tagline:
    en_us: Movie cards for your Telegram watch list
  description:
    en_us: Posts a card with poster, description and IMDb rating for every movie or series name or link sent to your Telegram channel or group.
```

### 3.3 Check that it works

The bot has no web page, so clicking its tile doesn't open anything. Open the logs instead: tile menu (⋮) →
*Settings* → *Terminal and Logs*, or over SSH:

```bash
docker logs -f movie-to-watch-bot
```

You should see `Bot started (language=uk-UA, …)`. Post a movie name in the group – a card should appear within a few
seconds.

## 4. Updating to a new version

1. On the Mac: build and push again (step 2) with a higher `VERSION`.
2. In CasaOS: tile menu (⋮) → **Check then update**. CasaOS downloads the new `latest` image and restarts the app.

If your CasaOS version has no such menu item, update over SSH. CasaOS keeps the app's compose file in
`/var/lib/casaos/apps/<app name>/`:

```bash
ls /var/lib/casaos/apps/                        # find the app's folder
cd /var/lib/casaos/apps/movie-to-watch-bot
sudo docker compose pull && sudo docker compose up -d
```

To go back to an older version, change the image tag in the app's settings from `latest` to e.g. `1.0.0` and save.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Multi-platform build is not supported for the docker driver` | You built without `--builder multiarch`, or skipped step 1.3. |
| `push access denied` / `insufficient_scope` / `unauthorized` | Run `docker login -u <dockerhub-user>` again; the token needs *Read & Write*, and the image name must start with your exact username. |
| CasaOS log says `exec format error` | The image was built for the wrong platform only. Check step 2's `imagetools inspect` output and rebuild with both platforms. |
| Log says `Conflict: terminated by other getUpdates request` | Another copy of the bot is running (on the Mac, or the old `docker compose` one on the Pi) – stop it (step 3.1). |
| `Missing required environment variables` in the log | A token wasn't filled in: tile menu (⋮) → *Settings* → *Environment variables*, then *Save*. |
| Bot runs but ignores messages in the group | It has to be a group **admin** (see README, step 2). |
