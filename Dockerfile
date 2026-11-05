# devbox などのプレビュー用。本番のデプロイ(deploy/)では使わない。
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# devbox は HOST / PORT を env で渡す。DEBUG=false でも静的ファイルを返すため --insecure を付ける(プレビュー専用)
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py seed_preview && exec python manage.py runserver 0.0.0.0:${PORT:-8000} --insecure"]
