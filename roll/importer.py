import csv
import io
import re
import unicodedata

from django.contrib.auth import get_user_model
from django.db import transaction

from .models import Position, RosterEntry


HEADER_ALIASES = {
    "種別": "entry_type",
    "type": "entry_type",
    "氏名": "name",
    "氏名・団体名": "name",
    "name": "name",
    "ふりがな": "name_kana",
    "氏名かな": "name_kana",
    "name_kana": "name_kana",
    "校内識別番号": "school_identifier",
    "学籍番号": "school_identifier",
    "student_id": "school_identifier",
    "grade": "grade",
    "学年": "grade",
    "組": "homeroom",
    "クラス": "homeroom",
    "homeroom": "homeroom",
    "番号": "student_number",
    "出席番号": "student_number",
    "student_number": "student_number",
    "部員": "is_member",
    "放送部員": "is_member",
    "is_member": "is_member",
    "アカウント": "account",
    "ユーザー名": "account",
    "username": "account",
    "役職": "positions",
    "役職名": "positions",
    "positions": "positions",
    "備考": "notes",
    "notes": "notes",
}

TYPE_ALIASES = {
    "生徒": RosterEntry.EntryType.STUDENT,
    "student": RosterEntry.EntryType.STUDENT,
    "教職員": RosterEntry.EntryType.FACULTY,
    "職員": RosterEntry.EntryType.FACULTY,
    "faculty": RosterEntry.EntryType.FACULTY,
    "staff": RosterEntry.EntryType.FACULTY,
    "校内団体": RosterEntry.EntryType.ORGANIZATION,
    "団体": RosterEntry.EntryType.ORGANIZATION,
    "organization": RosterEntry.EntryType.ORGANIZATION,
    "group": RosterEntry.EntryType.ORGANIZATION,
    "その他": RosterEntry.EntryType.OTHER,
    "other": RosterEntry.EntryType.OTHER,
}

TRUE_VALUES = {"1", "true", "yes", "y", "はい", "○"}
FALSE_VALUES = {"", "0", "false", "no", "n", "いいえ", "×"}


class RosterImportError(Exception):
    pass


def _decode_csv(uploaded_file):
    content = uploaded_file.read()
    for encoding in ("utf-8-sig", "cp932"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise RosterImportError("CSVの文字コードはUTF-8またはShift-JISにしてください。")


def _split_positions(value, row_number, positions_by_name):
    names = [name.strip() for name in value.replace("、", ",").replace(";", ",").split(",")]
    names = [name for name in names if name]
    missing = [name for name in names if name not in positions_by_name]
    if missing:
        raise RosterImportError(
            f"{row_number}行目: 未登録の役職があります: {', '.join(missing)}"
        )
    return [positions_by_name[name] for name in names]


def _parse_school_number(value, field_name, row_number, pattern):
    value = unicodedata.normalize("NFKC", value).strip()
    if not value:
        return ""
    match = re.fullmatch(pattern, value)
    if match is None:
        raise RosterImportError(
            f"{row_number}行目: {field_name}は指定された範囲の数字を選択してください。"
        )
    return match.group(1)


def _parse_student_number(value, row_number):
    value = unicodedata.normalize("NFKC", value).strip()
    if not value:
        return None
    if not value.isdecimal() or int(value) < 1:
        raise RosterImportError(
            f"{row_number}行目: 出席番号は1以上の数字を指定してください。"
        )
    return int(value)


def _parse_row(raw_row, row_number, positions_by_name, users_by_identifier):
    row = {
        HEADER_ALIASES[header.strip()]: (value or "").strip()
        for header, value in raw_row.items()
        if header and header.strip() in HEADER_ALIASES
    }
    if not row.get("name"):
        raise RosterImportError(f"{row_number}行目: 氏名・団体名が必要です。")

    raw_type = row.get("entry_type", "生徒").lower()
    entry_type = TYPE_ALIASES.get(raw_type)
    if entry_type is None:
        raise RosterImportError(f"{row_number}行目: 種別「{raw_type}」は無効です。")

    raw_member = row.get("is_member", "").lower()
    if raw_member not in TRUE_VALUES | FALSE_VALUES:
        raise RosterImportError(f"{row_number}行目: 部員の値は「はい」または「いいえ」にしてください。")
    is_member = raw_member in TRUE_VALUES
    if entry_type == RosterEntry.EntryType.ORGANIZATION and is_member:
        raise RosterImportError(f"{row_number}行目: 校内団体は部員に設定できません。")

    account_identifier = row.get("account", "")
    account = None
    if account_identifier:
        account = users_by_identifier.get(account_identifier.casefold())
        if account is None:
            raise RosterImportError(
                f"{row_number}行目: アカウント「{account_identifier}」が見つかりません。"
            )
        if entry_type == RosterEntry.EntryType.ORGANIZATION:
            raise RosterImportError(f"{row_number}行目: 校内団体にはアカウントを紐付けられません。")

    return {
        "entry_type": entry_type,
        "name": row["name"],
        "name_kana": row.get("name_kana", ""),
        "school_identifier": row.get("school_identifier") or None,
        "grade": _parse_school_number(
            row.get("grade", ""),
            "学年（1〜6）",
            row_number,
            r"(?:(?:高校|中学))?([1-6])(?:年生?)?",
        ),
        "homeroom": _parse_school_number(
            row.get("homeroom", ""),
            "組（1〜9）",
            row_number,
            r"([1-9])組?",
        ),
        "student_number": _parse_student_number(
            row.get("student_number", ""),
            row_number,
        ),
        "is_member": is_member,
        "account": account,
        "positions": _split_positions(
            row.get("positions", ""), row_number, positions_by_name
        ),
        "notes": row.get("notes", ""),
    }


def import_roster_csv(uploaded_file):
    text = _decode_csv(uploaded_file)
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    if not reader.fieldnames or not any(
        HEADER_ALIASES.get(header.strip()) == "name"
        for header in reader.fieldnames
        if header
    ):
        raise RosterImportError("CSVに「氏名」または「氏名・団体名」列が必要です。")

    positions_by_name = {
        position.name: position for position in Position.objects.filter(is_active=True)
    }
    user_model = get_user_model()
    users_by_identifier = {}
    for user in user_model.objects.all():
        users_by_identifier[user.username.casefold()] = user
        if user.email:
            users_by_identifier[user.email.casefold()] = user

    parsed_rows = []
    seen_identifiers = set()
    for row_number, raw_row in enumerate(reader, start=2):
        if None in raw_row:
            raise RosterImportError(
                f"{row_number}行目: ヘッダーより多くの列が指定されています。"
            )
        if not raw_row or not any(value and value.strip() for value in raw_row.values()):
            continue
        row = _parse_row(raw_row, row_number, positions_by_name, users_by_identifier)
        school_identifier = row["school_identifier"]
        if school_identifier:
            if school_identifier in seen_identifiers:
                raise RosterImportError(
                    f"{row_number}行目: 校内識別番号「{school_identifier}」がCSV内で重複しています。"
                )
            seen_identifiers.add(school_identifier)
        parsed_rows.append(row)

    if not parsed_rows:
        raise RosterImportError("CSVにインポートするデータがありません。")

    seen_account_ids = set()
    for row in parsed_rows:
        account = row["account"]
        if account is None:
            continue
        if account.pk in seen_account_ids:
            raise RosterImportError(
                f"アカウント「{account.username}」がCSV内で複数回指定されています。"
            )
        seen_account_ids.add(account.pk)
        linked_entry = (
            RosterEntry.objects.filter(account=account).only("pk").first()
        )
        if linked_entry is None:
            continue
        if row["school_identifier"]:
            target_entry = RosterEntry.objects.filter(
                school_identifier=row["school_identifier"]
            ).only("pk").first()
        else:
            target_entry = (
                RosterEntry.objects.filter(
                    school_identifier__isnull=True,
                    entry_type=row["entry_type"],
                    name=row["name"],
                    grade=row["grade"],
                    homeroom=row["homeroom"],
                )
                .only("pk")
                .first()
            )
        if target_entry is None or target_entry.pk != linked_entry.pk:
            raise RosterImportError(
                f"アカウント「{account.username}」は別の名簿に紐付け済みです。"
            )

    created_count = 0
    updated_count = 0
    with transaction.atomic():
        for row in parsed_rows:
            school_identifier = row["school_identifier"]
            if school_identifier:
                entry, created = RosterEntry.objects.get_or_create(
                    school_identifier=school_identifier,
                    defaults={key: value for key, value in row.items() if key != "positions"},
                )
            else:
                entry = RosterEntry.objects.filter(
                    school_identifier__isnull=True,
                    entry_type=row["entry_type"],
                    name=row["name"],
                    grade=row["grade"],
                    homeroom=row["homeroom"],
                ).first()
                created = entry is None
                if created:
                    entry = RosterEntry.objects.create(
                        **{key: value for key, value in row.items() if key != "positions"}
                    )
            if not created:
                for key, value in row.items():
                    if key != "positions":
                        setattr(entry, key, value)
                entry.save()
                updated_count += 1
            else:
                created_count += 1
            entry.positions.set(row["positions"])

    return created_count, updated_count
