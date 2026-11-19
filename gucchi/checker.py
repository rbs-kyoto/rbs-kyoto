import re
from datetime import date


SENTENCE_ENDINGS = ("。", "！", "？", ".", "!", "?")
DATE_RE = re.compile(
    r"(?:([0-9]{4})年)?([0-9]{1,2})月([0-9]{1,2})日"
)
WEEKDAY_RE = re.compile(r"([月火水木金土日])曜日")


def count_characters(text):
    return len(re.sub(r"\s", "", text))


def reading_seconds(character_count):
    return {
        "min": round(character_count / 350 * 60),
        "median": round(character_count / 325 * 60),
        "max": round(character_count / 300 * 60),
    }


def split_sentences(text):
    parts = re.split(r"(?<=[。！？!?])", text)
    return [part.strip() for part in parts if part.strip()]


def _invalid_or_matched_date(text):
    findings = []
    for match in DATE_RE.finditer(text):
        year_text, month_text, day_text = match.groups()
        year = int(year_text) if year_text else date.today().year
        month = int(month_text)
        day = int(day_text)
        try:
            found_date = date(year, month, day)
        except ValueError:
            findings.append(
                {
                    "code": "invalid_date",
                    "category": "date",
                    "message": f"{month_text}月{day_text}日は存在しない日付です。",
                    "start": match.start(),
                    "end": match.end(),
                }
            )
            continue

        weekday_match = WEEKDAY_RE.search(text[match.end(): match.end() + 20])
        if weekday_match:
            expected = ("月", "火", "水", "木", "金", "土", "日")[found_date.weekday()]
            actual = weekday_match.group(1)
            if expected != actual:
                findings.append(
                    {
                        "code": "weekday_mismatch",
                        "category": "date",
                        "message": (
                            f"日付と曜日が一致しません。"
                            f"{month_text}月{day_text}日は{expected}曜日です。"
                        ),
                        "start": match.start(),
                        "end": match.end() + weekday_match.end(),
                    }
                )
    return findings


def run_deterministic_check(text, target_seconds=None):
    character_count = count_characters(text)
    readings = reading_seconds(character_count)
    findings = []

    if character_count == 0:
        findings.append(
            {
                "code": "empty_text",
                "category": "text",
                "message": "原稿が空です。",
                "start": 0,
                "end": 0,
            }
        )

    if target_seconds is not None:
        median_seconds = readings["median"]
        difference = median_seconds - target_seconds
        if difference != 0:
            findings.append(
                {
                    "code": "target_length",
                    "category": "length",
                    "message": (
                        f"目安は{text_display_seconds(difference)}"
                        f"{'長い' if difference > 0 else '短い'}です。"
                    ),
                    "start": 0,
                    "end": character_count,
                }
            )

    offset = 0
    for sentence in split_sentences(text):
        if len(re.sub(r"\s", "", sentence)) > 60:
            findings.append(
                {
                    "code": "long_sentence",
                    "category": "sentence",
                    "message": "60字を超える文です。区切れるか確認してください。",
                    "start": offset,
                    "end": offset + len(sentence),
                }
            )
        offset += len(sentence)

    findings.extend(_invalid_or_matched_date(text))

    for match in re.finditer(r"\d+\s*(?:人|回|日|年|月|時|分|秒|台|本|枚|件)", text):
        findings.append(
            {
                "code": "number_reading",
                "category": "reading",
                "message": "数字・助数詞の読み方を確認してください。",
                "start": match.start(),
                "end": match.end(),
            }
        )

    return {
        "character_count": character_count,
        "reading_seconds": readings,
        "findings": findings,
    }


def text_display_seconds(seconds):
    absolute = abs(seconds)
    if absolute < 60:
        return f"{absolute}秒"
    minutes, remaining = divmod(absolute, 60)
    return f"{minutes}分{remaining}秒" if remaining else f"{minutes}分"
