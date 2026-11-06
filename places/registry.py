"""場所を使うアプリが、自分の「利用状況」を places に教えるための登録先。

places は、予定や機材など個別のアプリを知らない。使う側のアプリが ready() で
register_provider() を呼び、「この場所群・この期間に、何が入っているか」を返す関数を登録する。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, Iterable

from .models import Place


@dataclass(frozen=True)
class PlaceUse:
    source: str  # 提供者の名前(例: "schedule")
    key: object  # 提供元での id(例: 予定の pk)。自分自身を除外するときに使う
    title: str
    start: datetime
    end: datetime
    place: Place
    url: str


# 提供者: (場所の id の集合, 開始, 終了) -> PlaceUse の並び。期間は両端を含む。
Provider = Callable[[set, datetime, datetime], Iterable[PlaceUse]]

PROVIDERS: Dict[str, Provider] = {}


def register_provider(name: str, provider: Provider) -> None:
    PROVIDERS[name] = provider
