# 静的サイト化の概念実証（自宅Proxmox）

> **本番・部室PC用の手順は [`../docker/README.md`](../docker/README.md)（Docker 版）です。**
> 管理画面のボタンでの更新・復元と、救出画面は Docker 版にだけあります。
> この apt 版は、Docker を使わずに最小構成を試したいとき用に残しています。

本番（AWS）には触らず、CT 114 (10.2.1.14) で「管理はDjango、公開は静的HTML + PHP」の構成を試すための手順です。

## 構成

```
rbs-poc.clusters-prj.com        → Apache :80   gate/（PHP）＋書き出し済みHTML
rbs-poc-admin.clusters-prj.com  → Apache :8080 → daphne 127.0.0.1:8000（Django, SITE_ROLE=admin）
                                   ※ Cloudflare Access「管理者を許可」で保護

/srv/rbs-kyoto   このリポジトリ（feature/static-site-poc）
/srv/rbs-site    書き出し先（SITE_BUILD_ROOT）
    releases/v1, v2, ...   デプロイごとの書き出し
    current -> releases/vN 公開中のバージョン
```

- 管理画面で編集（右側に、入力中の内容でそのページのプレビューが出る）→ 「デプロイを管理」（`/deploy/`）でサイト全体をプレビュー → 説明を書いて「デプロイ」
- 過去のバージョンは一覧の「このバージョンを公開」でいつでも戻せる
- Djangoを止めても、公開サイトは最後にデプロイした内容のまま表示される
- 「システムの状態」（`/system/`）で、ドメインの期限やソフトのサポート終了日を1日1回確認する。コマンドなら `manage.py check_system`

## セットアップ（Ubuntu の CT 内で root として）

```sh
apt install apache2 libapache2-mod-php php-curl python3-venv git
a2enmod proxy proxy_http headers

useradd --system --home /srv/rbs-kyoto --shell /usr/sbin/nologin rbs
git clone -b feature/static-site-poc https://github.com/rbs-kyoto/rbs-kyoto.git /srv/rbs-kyoto
mkdir -p /srv/rbs-site
chown -R rbs:rbs /srv/rbs-kyoto /srv/rbs-site

cd /srv/rbs-kyoto
sudo -u rbs python3 -m venv .venv
sudo -u rbs .venv/bin/pip install -r requirements.txt
sudo -u rbs cp deploy/poc/env.example .env   # SECRET_KEY などを書き換える
sudo -u rbs .venv/bin/python manage.py migrate
sudo -u rbs .venv/bin/python manage.py collectstatic --noinput
sudo -u rbs .venv/bin/python manage.py createsuperuser

cp deploy/poc/rbs-admin.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now rbs-admin

cp gate/config.example.php gate/config.php    # Googleのクライアント情報を書く
chown root:www-data gate/config.php
chmod 640 gate/config.php

cp deploy/poc/apache/rbs-site.conf deploy/poc/apache/rbs-admin.conf /etc/apache2/sites-available/
a2dissite 000-default
a2ensite rbs-site rbs-admin
systemctl reload apache2
```

最初の1回は管理画面から「デプロイ」するか、次のコマンドで書き出します（書き出すまで公開側は503になります）。

```sh
sudo -u rbs .venv/bin/python manage.py publish_site -m "初回"
```

## Google OAuth

1. Google Cloud で「OAuth クライアント ID（ウェブアプリケーション）」を作る
2. 承認済みのリダイレクトURIに `https://rbs-poc.clusters-prj.com/accounts/google/login/callback/` を登録
3. クライアントIDとシークレットを `gate/config.php` に書く

自分のGmailで試すときは `allowed_domain` を `gmail.com` にします。

## Cloudflare Tunnel（ProxmoxTunnel1）

| ホスト名 | 転送先 | Access |
|---|---|---|
| rbs-poc.clusters-prj.com | http://10.2.1.14:80 | なし（ログインは gate/ が担当） |
| rbs-poc-admin.clusters-prj.com | http://10.2.1.14:8080 | 管理者を許可 |

## 本番のデータで試したいとき

AWS から `db.sqlite3` と `media/` をコピーして `/srv/rbs-kyoto/` に置き、`migrate` を実行してからデプロイします。

## コードを更新したとき

```sh
cd /srv/rbs-kyoto
sudo -u rbs git pull
sudo -u rbs .venv/bin/pip install -r requirements.txt
sudo -u rbs .venv/bin/python manage.py migrate
sudo -u rbs .venv/bin/python manage.py collectstatic --noinput
systemctl restart rbs-admin
```

テンプレートやCSSの変更は、管理画面からもう一度デプロイすると公開側に反映されます（DBの変更がなくても「デプロイ」は押せます）。
