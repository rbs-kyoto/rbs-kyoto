from django.db import models


class Place(models.Model):
    """サイト全体で共通の「場所」マスター(部室・体育館・棚など)。

    機材の保管場所と、予定の場所の両方がこれを参照する。
    もとは equipment.StorageLocation で、データ(主キー・テーブル)をそのまま引き継いでいる。
    """

    name = models.CharField("場所名", max_length=100)
    code = models.CharField("場所コード", max_length=30, blank=True)
    parent = models.ForeignKey(
        "self",
        verbose_name="上位の場所",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )
    description = models.TextField("詳細", blank=True)
    notes = models.TextField("備考", blank=True)
    is_active = models.BooleanField("使用中", default=True)
    is_storage = models.BooleanField("機材の保管場所として使う", default=True)
    is_venue = models.BooleanField("予定の場所として使う", default=False)

    class Meta:
        ordering = ["name"]
        verbose_name = "場所"
        verbose_name_plural = "場所"
        # equipment.StorageLocation から引き継いだテーブル・制約名。
        # 移行時にデータを動かさないため、あえて旧名のままにしている。
        db_table = "equipment_storagelocation"
        constraints = [
            models.UniqueConstraint(
                fields=["parent", "name"],
                name="equipment_unique_sibling_location",
            )
        ]

    def __str__(self):
        if self.parent_id:
            return f"{self.parent} / {self.name}"
        return self.name

    def ancestors(self):
        """上位の場所を、近い順に返す。"""
        result = []
        node = self.parent
        while node is not None and node.pk != self.pk:
            result.append(node)
            node = node.parent
        return result

    def descendant_ids(self):
        """下位の場所(孫以下も含む)の id を返す。"""
        found = []
        frontier = [self.pk]
        while frontier:
            children = list(
                Place.objects.filter(parent_id__in=frontier).values_list("pk", flat=True)
            )
            children = [pk for pk in children if pk not in found and pk != self.pk]
            found.extend(children)
            frontier = children
        return found

    def related_ids(self):
        """自分・上位・下位の id。親の部屋を押さえたら、その中の場所も使えない、という扱いに使う。"""
        return {self.pk, *(a.pk for a in self.ancestors()), *self.descendant_ids()}
