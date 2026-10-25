#!/usr/bin/env bash
# rbs京都を Docker で動かす環境を作る（Ubuntu Server 24.04 LTS を想定）。root で実行する。
#
#   sudo ./install.sh <GitのURL> [ブランチ名]
#
# 何度実行しても、すでにあるものは作り直さない（.env とパスワードは上書きしない）。
# 聞かれる内容は、環境変数で先に渡せば省略できる:
#   PUBLIC_HOST ADMIN_HOST GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET RESCUE_PASSWORD
# （WEB_PORT ADMIN_PORT で、コンテナがホストに開くポートも変えられる）
set -euo pipefail

REPO_URL="${1:?使い方: sudo ./install.sh <GitのURL> [ブランチ名]}"
BRANCH="${2:-main}"
RBS_HOME="${RBS_HOME:-/srv/rbs}"

[ "$(id -u)" -eq 0 ] || { echo "root で実行してください（sudo ./install.sh ...）。" >&2; exit 1; }
command -v docker >/dev/null || {
    echo "Docker が入っていません。先に入れてください: https://docs.docker.com/engine/install/ubuntu/" >&2
    exit 1
}
docker compose version >/dev/null || { echo "docker compose が使えません。Docker を最新にしてください。" >&2; exit 1; }
command -v git >/dev/null || { apt-get update && apt-get install -y git; }

ask() { # ask 変数名 説明 既定値
    local name="$1" prompt="$2" default="${3:-}" value
    if [ -n "${!name:-}" ]; then return; fi
    read -r -p "$prompt${default:+ [$default]}: " value
    printf -v "$name" '%s' "${value:-$default}"
}

echo "== 1/7 ユーザーとフォルダ"
id rbs >/dev/null 2>&1 || useradd --system --home "$RBS_HOME" --shell /usr/sbin/nologin rbs
RBS_UID="$(id -u rbs)"
RBS_GID="$(id -g rbs)"
mkdir -p "$RBS_HOME"/{state/data,state/site,backups,spool/requests,spool/results,spool/running,spool/logs}
chown -R rbs:rbs "$RBS_HOME/state"
chmod 755 "$RBS_HOME" "$RBS_HOME/backups" "$RBS_HOME/spool" "$RBS_HOME/spool/results" "$RBS_HOME/spool/logs"
chmod 1777 "$RBS_HOME/spool/requests"

echo "== 2/7 コードの取得"
if [ ! -d "$RBS_HOME/repo/.git" ]; then
    git clone -b "$BRANCH" "$REPO_URL" "$RBS_HOME/repo" || {
        echo >&2
        echo "リポジトリを取得できませんでした。非公開のリポジトリなら、先に deploy/docker/README.md の" >&2
        echo "「非公開リポジトリの取得」（デプロイキーかトークン）を済ませてください。" >&2
        exit 1
    }
fi

echo "== 3/7 設定ファイル（$RBS_HOME/.env）"
if [ ! -f "$RBS_HOME/.env" ]; then
    ask PUBLIC_HOST "公開サイトのホスト名" "www.rbs-kyoto.org"
    ask ADMIN_HOST "管理画面のホスト名" "admin.rbs-kyoto.org"
    ask GOOGLE_CLIENT_ID "GoogleのクライアントID（あとで .env に書いてもよい）" ""
    ask GOOGLE_CLIENT_SECRET "Googleのクライアントシークレット" ""
    SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')"
    umask 077
    cat > "$RBS_HOME/.env" <<EOF
RBS_HOME=$RBS_HOME
RBS_UID=$RBS_UID
RBS_GID=$RBS_GID
SECRET_KEY=$SECRET_KEY
PUBLIC_HOST=$PUBLIC_HOST
ADMIN_HOST=$ADMIN_HOST
PUBLIC_SITE_URL=https://$PUBLIC_HOST/
GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET=$GOOGLE_CLIENT_SECRET
GATE_ALLOWED_DOMAIN=rakunan-h.ed.jp
WEB_PORT=${WEB_PORT:-80}
ADMIN_PORT=${ADMIN_PORT:-8080}
EOF
    umask 022
else
    echo "すでにあるので、そのまま使います。"
fi

echo "== 4/7 救出画面のパスワード"
if [ ! -f "$RBS_HOME/rescue_password_hash" ]; then
    if [ -z "${RESCUE_PASSWORD:-}" ]; then
        read -r -s -p "救出画面のパスワード（12文字以上。紙に書いて保管してください）: " RESCUE_PASSWORD; echo
        [ "${#RESCUE_PASSWORD}" -ge 12 ] || { echo "12文字以上にしてください。" >&2; exit 1; }
    fi
    # パスワードはコマンドの引数に出さない（ps で見えてしまうため）
    docker run --rm -e P="$RESCUE_PASSWORD" php:8.4-cli php -r 'echo password_hash(getenv("P"), PASSWORD_DEFAULT);' \
        > "$RBS_HOME/rescue_password_hash"
    chmod 644 "$RBS_HOME/rescue_password_hash"
else
    echo "すでにあるので、そのまま使います。"
fi

COMPOSE=(docker compose -p rbs -f "$RBS_HOME/repo/deploy/docker/compose.yaml")
# その環境だけの設定を重ねたいとき（ポートの変更など）: RBS_COMPOSE_OVERRIDES=/path/a.yaml:/path/b.yaml
for override in ${RBS_COMPOSE_OVERRIDES//:/ }; do COMPOSE+=(-f "$override"); done
COMPOSE+=(--env-file "$RBS_HOME/.env")

echo "== 5/7 イメージのビルド（初回は数分かかります）"
"${COMPOSE[@]}" build

echo "== 6/7 DBの準備"
"${COMPOSE[@]}" run --rm admin python manage.py migrate --noinput
if [ ! -f "$RBS_HOME/.superuser-created" ]; then
    if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ]; then
        # 自動で入れるとき: DJANGO_SUPERUSER_USERNAME / _PASSWORD / _EMAIL を環境変数で渡す
        "${COMPOSE[@]}" run --rm -e DJANGO_SUPERUSER_USERNAME -e DJANGO_SUPERUSER_PASSWORD -e DJANGO_SUPERUSER_EMAIL \
            admin python manage.py createsuperuser --noinput
    else
        echo "管理画面にログインするユーザーを作ります。"
        "${COMPOSE[@]}" run --rm admin python manage.py createsuperuser
    fi
    touch "$RBS_HOME/.superuser-created"
fi
"${COMPOSE[@]}" up -d

echo "== 7/7 operator（操作ボタンと救出画面の作業を受け持つ常駐プログラム）"
if [ -d /run/systemd/system ]; then
    sed "s#@RBS_HOME@#$RBS_HOME#g" "$RBS_HOME/repo/deploy/docker/rbs-opsd.service" > /etc/systemd/system/rbs-opsd.service
    systemctl daemon-reload
    systemctl enable --now rbs-opsd
else
    echo "systemd が動いていないので、operator は自動起動に登録しませんでした。" >&2
    echo "  手動で起動するには: cd $RBS_HOME/repo && sudo env \$(grep -v '^#' $RBS_HOME/.env | xargs) python3 -m opsd" >&2
fi

source "$RBS_HOME/.env"
cat <<EOF

できました。次に、Cloudflare Tunnel の公開ホスト名を設定してください。

  $PUBLIC_HOST  →  http://localhost:$WEB_PORT      （Accessは付けない）
  $ADMIN_HOST   →  http://localhost:$ADMIN_PORT     （Cloudflare Access で管理者だけに限定）

Google のログイン用に、Google Cloud のリダイレクトURIへ次を登録してください。
  https://$PUBLIC_HOST/accounts/google/login/callback/

管理画面: https://$ADMIN_HOST/    救出画面: https://$ADMIN_HOST/rescue/
最初に、管理画面の「デプロイを管理」からデプロイすると、公開サイトが表示されます。
EOF
