# Backend

This directory contains the Django 6.1 service for Toolvaya.

## Environment

- Python 3.14.7
- Django 6.1
- PostgreSQL for persistent storage

## Bootstrap

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py runserver
```

## PostgreSQL

For local PostgreSQL, start the container from the repository root:

```bash
docker compose up -d postgres
```

Then set `DATABASE_ENGINE=django.db.backends.postgresql` in `backend/.env` and adjust the database credentials if needed.

## Async PDF processing

The PDF app uses Celery with Redis. For local development, start Redis too:

```bash
docker compose up -d redis
```

Run a worker from the backend directory with:

```bash
backend\.venv\Scripts\celery -A config worker -l info
```

## Environment variables

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `DATABASE_ENGINE`
- `DATABASE_NAME`
- `DATABASE_USER`
- `DATABASE_PASSWORD`
- `DATABASE_HOST`
- `DATABASE_PORT`

## API docs

- Swagger UI: `/api/docs/`
- OpenAPI schema: `/api/schema/`
- ReDoc: `/api/redoc/`
