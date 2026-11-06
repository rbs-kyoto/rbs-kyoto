# 場所マスター(places)

サイト全体で共通に使う「場所」(校舎・放送室・体育館・棚など)のマスターです。もとは機材の「保管場所」(`equipment.StorageLocation`)で、**テーブルと主キーをそのまま引き継いで** `places.Place` に移しました。

## 管理

- 画面: `/places/`(staff のみ。トップページの Apps にも出ます)。管理画面(`/admin/`)からも編集できます。
- 場所は上位・下位の階層を持てます(例: 校舎 / 放送室 / ブース)。
- 場所ごとに用途を選びます。
  - **予定の場所として使う**(`is_venue`): 予定のフォームで選べるようになります。
  - **機材の保管場所として使う**(`is_storage`): 機材のフォームで選べるようになります。
- 移行前から機材で使っていた場所は「機材の保管場所」のままで、「予定の場所」にはなっていません。予定で使う場所は、`/places/` で「予定の場所」にチェックしてください。

## 予定の場所と競合チェック

- 予定の場所は、この場所マスターから選びます(自由入力はなくなりました)。
- 同じ場所に重なる予定があると、予定の詳細で警告します。フォームでも、場所と日時を入れた時点で警告します。**警告だけで、保存はできます。**
- **上位・下位の場所も同じ場所として扱います。** 「校舎」を押さえている間は「放送室」も使えない、という扱いです。
- 終日の予定は、その日いっぱいを使うものとして扱います。繰り返し予定は、回ごとに判定します。
- 移行時、以前の自由入力の場所は、名前が1件だけ一致する場所があればそれに紐付けました(その場所は「予定の場所」になります)。一致しない・複数あって決められないものは、メモの先頭に `【場所】…` として残しています。

## Python の共通関数(アプリ間で使う)

`places.services` を import します。

```python
from places import services

services.venues()                          # 予定の場所として選べる場所(QuerySet)
services.storage_places()                  # 機材の保管場所として選べる場所
services.find_conflicts(place, start, end) # その場所(と上位・下位)を start〜end に使っているもの
services.is_available(place, start, end)
```

`find_conflicts` の `exclude={"schedule": event.pk}` で、編集中の予定自身などを除けます。戻り値は `PlaceUse`(`source`, `key`, `title`, `start`, `end`, `place`, `url`)のリストです。

### 自分のアプリの利用状況を提供する

`places` は個別のアプリを知りません。場所を使うアプリが、`AppConfig.ready()` で提供者を登録します(予定は `schedule/apps.py` が登録しています)。

```python
from places.registry import PlaceUse, register_provider

def provide(place_ids, start, end):
    # place_ids のいずれかを使っていて、start〜end(両端を含む)と重なるものを返す
    for booking in Booking.objects.filter(...):
        yield PlaceUse(source="booking", key=booking.pk, title=..., start=..., end=..., place=booking.place, url=...)

register_provider("booking", provide)
```

登録すると、`find_conflicts` と JSON API の両方に、そのアプリの利用状況が含まれます。

## JSON API(読み取り専用)

ログイン済みのセッション(Cookie)で使います。未ログインは `401`、不正な指定は `400` と `{"error": "..."}` を返します。

| パス | 内容 |
|---|---|
| `GET /api/places/` | 一覧。`kind=venue\|storage\|all`(既定 all)、`q=名前`、`include_inactive=1` |
| `GET /api/places/<id>/` | 詳細(上位の場所と、直下の場所つき) |
| `GET /api/places/<id>/usage/?start=…&end=…` | その期間の空き状況。`available` と `conflicts`(重なる利用) |

`start` / `end` は ISO 8601 です。`2026-11-14T09:00`(時刻のみの指定は日本時間)、`2026-11-14T09:00:00+09:00`、`2026-11-14`(日付だけなら、その日全体)が使えます。期間は最大366日です。`exclude=schedule:12`(複数可)で、編集中の予定などを除外できます。

```json
{
  "place": {"id": 3, "name": "放送室", "path": "校舎 / 放送室", "...": "..."},
  "start": "2026-11-14T14:00:00+09:00",
  "end": "2026-11-14T15:00:00+09:00",
  "available": false,
  "conflicts": [
    {"source": "schedule", "title": "校内放送の収録",
     "start": "2026-11-14T13:00:00+09:00", "end": "2026-11-14T16:00:00+09:00",
     "place_id": 3, "place_path": "校舎 / 放送室", "url": "/schedule/1/?date=2026-11-14"}
  ]
}
```

## デプロイ時の注意

- マイグレーションを適用してください。機材の保管場所は、データを動かさず(同じテーブル・主キーのまま)付け替えます。
- DB上のテーブル名は、移行前のまま `equipment_storagelocation` です(データを動かさないため。名前だけの問題で、動作には影響しません)。
