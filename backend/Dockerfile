FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/bulletfeed

COPY pyproject.toml README.md ./
COPY app ./app
COPY scripts ./scripts
RUN python -m pip install --upgrade pip && python -m pip install .

RUN useradd --create-home --uid 10001 bulletfeed \
    && mkdir -p /data /backups \
    && chown -R bulletfeed:bulletfeed /srv/bulletfeed /data /backups
USER bulletfeed

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
