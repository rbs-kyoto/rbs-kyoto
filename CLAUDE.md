# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A Django 6.1 site for RBS Kyoto with two apps:

- **`main`** — public-facing site: homepage pickups carousel and a News section (list, paginated detail view). Models: `Pickup`, `News` (rich text via `django-ckeditor-5`).
- **`accounts`** — custom user auth: login/logout, mypage, profile edit, password change. Uses a custom `User` model (`accounts.User`, subclass of `AbstractUser` with an added `display_name` field) — set as `AUTH_USER_MODEL`.

Views are function-based and intentionally simple (no DRF/API layer, no class-based views). Templates live in a single top-level `templates/` directory (not per-app), split into `templates/main/` and `templates/accounts/`. Static assets are similarly centralized under `static/main/` (css/js/img), not per-app.

`channels`/`daphne` and ASGI are wired up (`config.asgi.application`, `ASGI_APPLICATION` set) but there are no consumers/routing defined yet — the app currently runs as a standard synchronous Django app.

## Commands

Activate the venv first if one exists (`.venv/`), then use `manage.py` as usual:

```bash
python manage.py runserver
python manage.py migrate
python manage.py makemigrations
python manage.py test                     # run all tests
python manage.py test accounts            # run one app's tests
python manage.py test accounts.tests.ClassName.test_method  # single test
python manage.py createsuperuser
python manage.py collectstatic
```

Install dependencies with `pip install -r requirements.txt`.

## Configuration

- Settings (`config/settings.py`) load from a `.env` file at the repo root via `python-dotenv`. Required/expected env vars: `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` (comma-separated), `CSRF_TRUSTED_ORIGINS` (comma-separated). There is no `.env.example` — check with the user before assuming values.
- Database is SQLite (`db.sqlite3`) in all environments currently.
- Email backend is defined under a custom `MAILERS` setting (console backend), not Django's standard `EMAIL_BACKEND`.
- `AUTH_USER_MODEL = 'accounts.User'` — always reference the user model via `get_user_model()` / `settings.AUTH_USER_MODEL`, never import `django.contrib.auth.models.User` directly.

## Conventions to follow

- News body content (`News.caption`) is CKEditor5 HTML; use the `has_caption` model property (strips tags/whitespace) rather than truthiness checks on `caption` directly when deciding whether to render it.
- Both `Pickup` and `News` use an `is_active` flag for soft-hiding from public views — public queries should filter on it (see `main/views.py`); admin list views expose it via `list_editable`.
- Japanese is used for user-facing strings (error messages, model verbose names) — match this when adding new user-facing text in `main`/`accounts`.
