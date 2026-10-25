# Docker で動かす（部室PCなどの本番）

管理画面（Django）と公開サイト（Apache + PHP）を別々のコンテナで動かします。
更新・再起動・バックアップ・復元は、**コマンドを打たずに管理画面のボタンでできます**。
Django が壊れても、別プロセスの救出画面から元に戻せます。

## 構成

```
部室PC（Ubuntu Server 24.04 LTS + Docker）
 ├─ web 　　コンテナ  Apache + PHP
 │    ├─ :80    公開サイト（書き出し済みHTML + gate/ のGoogleログイン）
 │    └─ :8080  管理画面ホスト
 │              ├─ /rescue/  救出画面（PHP。Django が止まっていても動く）
 │              └─ それ以外  → admin コンテナへ転送
 ├─ admin 　コンテナ  Django（管理画面。編集・プレビュー・デプロイ・操作ボタン）
 └─ opsd 　 ホストの常駐プログラム（systemd）
      操作ボタンと救出画面の「依頼」を受けて、決まった作業だけを実行する
```

- **Django には Docker の権限を渡していません。** ボタンを押すと、共有フォルダに「依頼」を書くだけです。
  実際に動かすのは opsd で、依頼の種類は決まったものしか受け付けません。
- 公開サイトは、最後にデプロイした内容を Apache が返すだけなので、Django が止まっても表示され続けます。

## 置き場所（`/srv/rbs`）

| 場所 | 中身 |
|---|---|
| `.env` | 設定とパスワード類（`install.sh` が作る。中身は人に見せない） |
| `rescue_password_hash` | 救出画面のパスワードのハッシュ |
| `repo/` | GitHub から取得したコード（イメージのビルド元） |
| `state/data/` | データ本体：`db.sqlite3` と `media/`（画像） |
| `state/site/` | デプロイで書き出した公開サイト（`releases/` と `current`） |
| `backups/` | バックアップ。1つ1つが `db.sqlite3` + `media/` + `meta.json` |
| `spool/` | 依頼と結果の受け渡し。`spool/logs/opsd.log` は opsd のログ |

## インストール

1. Ubuntu Server 24.04 LTS を入れ、[Docker をインストール](https://docs.docker.com/engine/install/ubuntu/)する。
   `sudo timedatectl set-timezone Asia/Tokyo` も実行する。
2. 次を実行する（GitHub のリポジトリを非公開にしている場合は、先にこのPC用のデプロイキーかトークンを用意する）。

   ```sh
   git clone https://github.com/rbs-kyoto/rbs-kyoto.git /tmp/rbs-install
   sudo /tmp/rbs-install/deploy/docker/install.sh https://github.com/rbs-kyoto/rbs-kyoto.git main
   ```

   ホスト名、Google のクライアントID、救出画面のパスワード、管理画面にログインするユーザーを聞かれます。
   **救出画面のパスワードは12文字以上にして、紙に書いて保管してください。**
3. Cloudflare Tunnel の公開ホスト名を設定する。

   | ホスト名 | 転送先 | Cloudflare Access |
   |---|---|---|
   | `www.rbs-kyoto.org` | `http://localhost:80` | 付けない（部員向けのログインは `gate/` が担当） |
   | `admin.rbs-kyoto.org` | `http://localhost:8080` | **付ける**（管理者だけ） |

4. Google Cloud の OAuth クライアントに、リダイレクトURI
   `https://www.rbs-kyoto.org/accounts/google/login/callback/` を登録する。
5. 本番のデータを引き継ぐ場合は、止めた状態で `db.sqlite3` を `state/data/`、画像を `state/data/media/` に置き、
   `sudo chown -R rbs:rbs /srv/rbs/state` を実行する。
6. 管理画面（`https://admin.rbs-kyoto.org/`）の「デプロイを管理」から最初のデプロイをすると、公開サイトが表示される。

`install.sh` は何度実行しても、すでにある設定やパスワードは上書きしません。

## 普段の操作（管理画面の「システムの操作」）

| ボタン | すること |
|---|---|
| 公開サイト（Apache・PHP）を更新 | 最新のコードと、PHP・OSのセキュリティ修正を取り込んで作り直す |
| 管理画面（Django）を更新 | 更新前にバックアップ → 作り直し → DBの更新 → 起動確認。1〜2分、管理画面が使えなくなる |
| バックアップを取る | データを今の状態で保存する |
| 再起動 / ログを見る | admin・web・opsd それぞれ |

- **更新に失敗すると、自動で元の版とデータに戻ります**（途中で DB を更新していても、更新前のバックアップから戻します）。
- バックアップは**毎日午前3時**にも自動で取り、種類ごとに新しい順で10〜14世代を残します。
- コードの更新は、GitHub の最新（`git pull --ff-only`）を取り込みます。大きなバージョンアップ
  （Django や Python の大きな更新）は、詳しい人に相談してから行ってください。
  管理画面の「システムの状態」に、サポート終了日が近いものが出ます。

## 管理画面が開かなくなったとき（救出画面）

`https://admin.rbs-kyoto.org/rescue/`（管理画面が止まっているときは、自動でここへの案内が出ます）。
救出画面のパスワードでログインします（失敗が5回続くと10分ロックされます）。

| 状況 | すること |
|---|---|
| 管理画面を更新したら動かなくなった | 「**更新前の状態に戻す**」。データと管理画面の版が、更新の直前に戻る |
| データを壊してしまった | 「バックアップから復元」で時点を選ぶ（復元する前の状態も自動で保存される） |
| 原因を知りたい | 「ログを見る」（admin・web・opsd） |
| とりあえず再起動したい | 「admin を再起動」「web を再起動」 |

復元は「復元」と入力しないと実行できません。復元した時点より後に編集した内容は消えます。

## どれも動かないとき

- 救出画面も開かない → web コンテナが止まっています。PCにログインして `sudo docker compose -p rbs -f /srv/rbs/repo/deploy/docker/compose.yaml --env-file /srv/rbs/.env up -d`
- 救出画面で依頼しても進まない → opsd が止まっています。`sudo systemctl restart rbs-opsd`（ログは `journalctl -u rbs-opsd`）
- PC自体が起動しない → 部室PCの故障です。`backups/` を（できれば別の場所にも）コピーしておけば、同じ手順で別のPCに復旧できます

## 注意

- **バックアップは同じPCの中にあります。** PCが壊れると一緒に失われるので、
  定期的に `/srv/rbs/backups`（最新の数個で十分）を別の場所（Googleドライブなど）にコピーしてください。
- 停電からの復旧のため、BIOSで「電源が戻ったら自動で起動」を有効にしてください。
  Docker と opsd は、PC起動時に自動で立ち上がります。
- テストや、ポートを変えたいときは、`.env` の `WEB_PORT` / `ADMIN_PORT` を変えます。
  環境ごとの追加設定は、`RBS_COMPOSE_OVERRIDES=/path/a.yaml:/path/b.yaml`（opsd と install.sh が読む）で重ねられます。
