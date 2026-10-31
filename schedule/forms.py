from django import forms
from django.utils import timezone

from .models import Event

DATETIME_INPUT = "%Y-%m-%dT%H:%M"


class EventForm(forms.ModelForm):
    start = forms.DateTimeField(
        label="開始",
        input_formats=[DATETIME_INPUT],
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"}, format=DATETIME_INPUT
        ),
    )
    end = forms.DateTimeField(
        label="終了",
        required=False,
        input_formats=[DATETIME_INPUT],
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"}, format=DATETIME_INPUT
        ),
    )
    recurrence_until = forms.DateField(
        label="繰り返しの終了日",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )

    class Meta:
        model = Event
        fields = [
            "title",
            "start",
            "end",
            "all_day",
            "location",
            "description",
            "recurrence",
            "recurrence_until",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start")
        end = cleaned.get("end")
        until = cleaned.get("recurrence_until")
        recurrence = cleaned.get("recurrence")

        if start and cleaned.get("all_day"):
            # 終日は日付のみ扱う(開始は 0:00 に揃える)
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            cleaned["start"] = start
            if end:
                end = end.replace(hour=0, minute=0, second=0, microsecond=0)
                cleaned["end"] = end

        if start and end and end < start:
            self.add_error("end", "終了は開始より後にしてください。")

        if recurrence == Event.Recurrence.NONE:
            cleaned["recurrence_until"] = None
        elif start and until and until < timezone.localtime(start).date():
            self.add_error("recurrence_until", "終了日は開始日以降にしてください。")

        return cleaned
