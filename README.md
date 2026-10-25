# rbs-kyoto（洛南高校放送部のサイト）

放送部の公開サイトと、その管理画面です。

> **このブランチ（`feature/static-site-poc`）は、新しい構成の概念実証です。**
> 自宅の Proxmox で動かして確かめている段階で、本番（`main`）にはまだ入っていません。

## 構成の考え方

公開サイトと管理画面を**別のものにして**、管理画面が壊れても、公開サイトが見られ続けるようにしています。

```
訪問者 ──→ Cloudflare ──→ 部室PC
                           ├─ 公開サイト（Apache + PHP）  書き出し済みのHTMLを返すだけ。部員向けページは Google ログインで判定（gate/）
                           ├─ 管理画面（Django）          記事の編集・プレビュー・デプロイ・操作ボタン。普段は管理者だけが使う
                           ├─ 救出画面（PHP）             Django が壊れても動く、固定パスワードの最小の画面
                           └─ operator（opsd）            操作ボタン・救出画面の「依頼」を受けて、決まった作業だけを実行する
```

- 公開サイトは、管理画面で「デプロイ」した内容を Apache が返すだけです。**Django が止まっても表示され続けます。**
- 管理画面は Docker に入っています。更新・再起動・バックアップ・復元は、**コマンドなしで、画面のボタンでできます**。
- 更新に失敗したら、自動で元の版とデータに戻ります。それでも動かないときは、救出画面から戻せます。
- サーバーが止まっても出る**メンテナンス画面**は、Cloudflare の機能だけで作っています（追加費用なし）。
- 毎週の自動更新（公開サイト用サーバー）、毎日のバックアップ、OS のセキュリティ更新は、自動です。

## なぜ Apache と Django を並べているのか（交互に支える）

Django（管理画面）は、更新でいちばん壊れやすい部品です。そこで、**種類の違う2つのプログラムを並べて、片方が壊れても、もう片方で立て直せる**ようにしています。

| | Apache + PHP | Django |
|---|---|---|
| 役目 | 公開サイトを返す。救出画面を動かす | 記事の編集・デプロイ・操作ボタン |
| 壊れやすさ | 変えることが少なく、**めったに壊れない** | 更新のたびに壊れる可能性がある |
| 片方が止まると | 公開サイトと救出画面は、**動き続ける** | 管理画面だけが使えない |

- **Django が死んだとき** → Apache 側の**救出画面**が動いているので、そこから「更新前に戻す」「バックアップから復元」「ログを見る」ができます。
- **Apache が死んだとき**（更新の失敗など）→ 管理画面（Django）から、ログを見て、再起動や更新前への復旧ができます。
- 2つは、**別のコンテナ・別の言語・別のプロセス**です。どちらも、同じ更新で、同時に壊れにくくしています（公開サイト用と管理画面は、別のボタンで、別々に更新します）。
- さらに、どちらも**直接は Docker を触りません**。「依頼」を共有フォルダに書くと、ホスト上の operator（`opsd`）が、決まった作業だけを実行します。operator が止まっても、systemd が自動で立て直します。
- 公開サイトが見られなくなる、サーバー全体の停止のときは、Cloudflare 側の**メンテナンス画面**が、最後の砦です。

つまり、**Django → Apache（救出画面）→ operator → systemd → Cloudflare** と、各層が、前の層の失敗を受け止めます。

## 読む順番

| 知りたいこと | 読むもの |
|---|---|
| 部室PCに入れる・日々の操作・困ったとき | [`deploy/docker/README.md`](deploy/docker/README.md)（**まずこれ**） |
| メンテナンス画面（Cloudflare）の準備・使い方 | [`deploy/cloudflare/README.md`](deploy/cloudflare/README.md) |
| Docker を使わない、最小の試験構成 | [`deploy/poc/README.md`](deploy/poc/README.md) |

## フォルダの案内

| フォルダ | 役目 |
|---|---|
| `main/` `manuals/` `video_archive/` `pickup/` ほか | サイトの中身（Django のアプリ） |
| `publisher/` | 書き出し（デプロイ）とプレビュー、バージョン管理 |
| `gate/` | 公開側の PHP。Google ログインで、公開版・部員向け版を出し分ける |
| `rescue/` | 救出画面（PHP） |
| `opsd/` | operator。ホスト上の常駐プログラム（標準ライブラリだけ）。Cloudflare のメンテナンス切り替えもここ |
| `operations/` | 管理画面の「システムの操作」 |
| `maintenance/` | 「設定 → メンテナンス」（予定の登録） |
| `system_status/` | 「システムの状態」（ドメイン・ソフトの期限の確認） |
| `deploy/` | 入れ方（Docker・Cloudflare・apt 版）と設定ファイル |

## 開発者向け

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
SECRET_KEY=dev python manage.py test          # 全部のテスト
python -m unittest opsd.tests opsd.test_rescue opsd.test_maintenance opsd.test_cloudflare_setup   # operator 側
```

- `main` の `errors.tests.ErrorPreviewTests.test_mypage_only_shows_error_preview_to_superusers` は、このブランチより前から失敗しています。
- 管理画面は `SITE_ROLE=admin`、公開側の確認は `SITE_ROLE=site` で、使う URL の組が変わります。
- Django は、Docker や Cloudflare を**直接は操作しません**。必ず、`spool/requests/` に「依頼」を書き、operator が実行します（`opsd/protocol.py` が、受け付ける依頼の一覧です）。

## 引き継ぐ人へ

プログラムが分からなくても、次の範囲は、管理画面と救出画面だけで運用できます。

- 記事・ピックアップ・マニュアルなどの編集と、公開（デプロイ）
- 更新・再起動・バックアップ・復元・ログの確認・メンテナンス画面
- 管理画面が開かないとき → 救出画面（`https://（管理画面のホスト）/rescue/`、パスワードは紙に保管）

**人に渡すときに、確認しておくもの**

- [ ] ドメインの契約者と、更新日（「システムの状態」に出ます）
- [ ] Cloudflare のアカウントの持ち主と、2要素認証の復旧手段
- [ ] Google Cloud（OAuth）のプロジェクトの持ち主と、公開ステータス
- [ ] GitHub のリポジトリの管理者権限（更新が、ここからソースを取ります）
- [ ] 救出画面のパスワードの保管場所
- [ ] 部室PCの置き場所・電源・ネットワーク（停電のあとは、自動で起動する設定にする）
- [ ] バックアップの、PC外へのコピー（今は同じPCの中だけです）
