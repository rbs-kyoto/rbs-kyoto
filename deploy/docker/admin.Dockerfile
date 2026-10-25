FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SITE_ROLE=admin \
    DATA_DIR=/state/data \
    SITE_BUILD_ROOT=/state/site \
    STATIC_MANIFEST=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# 管理画面のCSS・JSを集める（コンテナの中の WhiteNoise がそのまま配信する）
RUN SECRET_KEY=build-only python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
