FROM python:3.14-slim

LABEL org.opencontainers.image.title="Movies To Watch Bot" \
      org.opencontainers.image.source="https://github.com/xpert13/MovieToWatchBot"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY moviebot ./moviebot

USER nobody
CMD ["python", "-m", "moviebot"]
