import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


CATEGORIES = [
    ("A", "音響機器", "Audio", "ミキサー、マイク、ヘッドホン、アンプ、スピーカー"),
    ("B", "放送・送出機器", "Broadcast", "放送送出装置、インカム親機、業務用送出機器"),
    ("C", "カメラ・撮影機器", "Camera", "ビデオカメラ、レンズ、三脚、撮影リグ"),
    ("D", "記録媒体・データ機器", "Data & Storage", "SDカード、SSD、HDD、USBメモリ、カードリーダー"),
    ("E", "電源・電気機器", "Electrical", "ACアダプター、電源タップ、UPS、電源分配器"),
    ("F", "什器・設備", "Furniture & Fixtures", "機材ラック、ケース棚、机、椅子、スタンド"),
    ("G", "支持・固定器具", "Grip & Rigging", "クランプ、マウント、プレート、固定金具"),
    ("H", "工具・保守用品", "Hardware", "ドライバー、六角レンチ、圧着工具、保守工具"),
    ("I", "情報・コンピューター機器", "IT & Computing", "PC、モニター、キーボード、マウス、ネットワーク機器"),
    ("J", "接続・分配機器", "Junction & Distribution", "映像分配器、音声分配器、変換器、接続機器"),
    ("K", "セット・一式管理", "Kits", "撮影キット、マイクセット、救急セット、工具セット"),
    ("L", "照明機器", "Lighting", "LEDライト、照明スタンド、調光器、照明用アクセサリー"),
    ("M", "媒体・消耗品", "Media & Consumables", "テープ、ラベル、電池、記録用ディスク、クリーニング用品"),
    ("N", "通信・ネットワーク機器", "Network & Communications", "ルーター、LAN機器、無線機、トランシーバー"),
    ("O", "光学機器", "Optics", "双眼鏡、ファインダー関連、光学フィルター"),
    ("P", "制作・編集機器", "Production", "編集用コントローラー、映像キャプチャー、制作周辺機器"),
    ("Q", "測定・検査機器", "Quality & Test", "テスター、波形・信号確認機器、測定器"),
    ("R", "録音・収録機器", "Recording", "ICレコーダー、フィールドレコーダー、音声収録デッキ"),
    ("S", "切替・信号処理機器", "Switching & Signal", "ビデオスイッチャー、コンバーター、エンベッダー、同期信号機器"),
    ("T", "伝送・中継機器", "Transmission", "映像伝送機器、ワイヤレス映像送受信機、光伝送機器"),
    ("U", "汎用備品・作業用品", "Utility", "台車、養生用品、結束用品、運搬用具"),
    ("V", "映像表示機器", "Video & Display", "液晶モニター、プロジェクター、ビデオウォール"),
    ("W", "事務用品・文具", "Writing & Office", "ペン、ノート、ファイル、クリップ、コピー用紙"),
    ("X", "その他の周辺機器", "Accessories", "用途が特定分類に属さない専用アクセサリー"),
    ("Y", "安全・防災用品", "Safety & Security", "養生テープ、安全ベスト、手袋、救急用品、保護具"),
    ("Z", "保管・資料・その他", "Archive & Miscellaneous", "取扱説明書、台帳、保管資料、分類不能品"),
]


def create_categories_and_assign_existing_equipment(apps, schema_editor):
    Category = apps.get_model("equipment", "Category")
    Equipment = apps.get_model("equipment", "Equipment")
    database = schema_editor.connection.alias

    categories = {}
    for code, name, english_name, examples in CATEGORIES:
        category, _ = Category.objects.using(database).get_or_create(
            code=code,
            defaults={
                "name": name,
                "english_name": english_name,
                "examples": examples,
            },
        )
        categories[code] = category.pk

    for equipment in Equipment.objects.using(database).all().iterator():
        equipment.category_ref_id = categories[equipment.category]
        equipment.save(using=database, update_fields=["category_ref"])


class Migration(migrations.Migration):
    dependencies = [
        ("equipment", "0003_alter_qrdesign_background_alter_qrdesign_foreground_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Category",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "code",
                    models.CharField(
                        max_length=1,
                        unique=True,
                        validators=[
                            django.core.validators.RegexValidator(
                                message="分類記号はA〜Zの大文字1文字で指定してください。",
                                regex="^[A-Z]$",
                            )
                        ],
                        verbose_name="分類記号",
                    ),
                ),
                ("name", models.CharField(max_length=100, verbose_name="分類名")),
                (
                    "english_name",
                    models.CharField(max_length=100, verbose_name="英語名"),
                ),
                ("examples", models.TextField(blank=True, verbose_name="主な対象")),
            ],
            options={
                "verbose_name": "備品分類",
                "verbose_name_plural": "備品分類",
                "ordering": ["code"],
            },
        ),
        migrations.AddField(
            model_name="equipment",
            name="category_ref",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="equipment_items",
                to="equipment.category",
                verbose_name="分類",
            ),
        ),
        migrations.RunPython(
            create_categories_and_assign_existing_equipment,
            migrations.RunPython.noop,
        ),
        migrations.RemoveIndex(
            model_name="equipment",
            name="equipment_e_categor_458d69_idx",
        ),
        migrations.RemoveField(
            model_name="equipment",
            name="category",
        ),
        migrations.RenameField(
            model_name="equipment",
            old_name="category_ref",
            new_name="category",
        ),
        migrations.AlterField(
            model_name="equipment",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="equipment",
                to="equipment.category",
                verbose_name="分類",
            ),
        ),
        migrations.AlterField(
            model_name="equipment",
            name="inventory_number",
            field=models.CharField(max_length=20, unique=True, verbose_name="備品番号"),
        ),
        migrations.AddIndex(
            model_name="equipment",
            index=models.Index(
                fields=["category", "is_active"],
                name="equipment_e_categor_221f6a_idx",
            ),
        ),
    ]
