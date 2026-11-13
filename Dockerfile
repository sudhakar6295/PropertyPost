FROM ghcr.io/astral-sh/uv:0.8.11 AS uv
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy \
    UV_NO_DEV=1 UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN DJANGO_SETTINGS_MODULE=propertypost.settings.build uv run --no-sync manage.py collectstatic --noinput
RUN groupadd --system app && useradd --system --gid app --home /app app \
    && chown -R app:app /app
USER app
EXPOSE 8080
CMD ["uv", "run", "--no-sync", "gunicorn", "propertypost.wsgi:application", \
     "--bind", "0.0.0.0:8080", "--workers", "2", "--access-logfile", "-", \
     "--access-logformat", "%(h)s %(s)s %(b)s"]
