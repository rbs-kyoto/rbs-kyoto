from django import forms


class RosterImportForm(forms.Form):
    csv_file = forms.FileField(
        label="CSVファイル",
        help_text=(
            "UTF-8またはShift-JIS形式。氏名列は必須です。"
            "校内識別番号がある場合は同じ番号の名簿を更新します。"
        ),
    )

    def clean_csv_file(self):
        uploaded_file = self.cleaned_data["csv_file"]
        if not uploaded_file.name.lower().endswith(".csv"):
            raise forms.ValidationError("拡張子が.csvのファイルを選択してください。")
        if uploaded_file.size > 10 * 1024 * 1024:
            raise forms.ValidationError("CSVファイルは10MB以下にしてください。")
        return uploaded_file
