"""リッチテキストの無害化。

News.caption はテンプレートで |safe を通して描画される。CKEditorのツールバーが
限られているのは画面上だけの制約で、フォームに直接POSTすれば任意のHTMLを保存
できてしまうため、保存時にここで許可リストへ落とす。
"""

import nh3

# CKEDITOR_5_CONFIGS["extends"] のツールバー（見出し・太字・斜体・リンク・箇条書き）が
# 生成しうるタグと、ドラッグ&ドロップで挿入される画像まわりを許可する。
ALLOWED_TAGS = {
    "p", "br", "hr",
    "strong", "b", "em", "i", "u", "s",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li",
    "blockquote", "code", "pre",
    "a", "img", "figure", "figcaption",
    "span",
}

ALLOWED_ATTRIBUTES = {
    # rel は link_rel が全リンクに強制付与するので、ここでは受け付けない。
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "width", "height"},
    "figure": {"class"},
    "span": {"class"},
}

# javascript: と data: を弾く。アップロード画像は /media/ の相対URLになるため
# スキーム無しのURLはそのまま通る。
ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}


def sanitize_richtext(html):
    """許可リストに無いタグ・属性・URLスキームを取り除いたHTMLを返す。"""
    if not html:
        return ""

    return nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
        link_rel="noopener noreferrer",
    )
