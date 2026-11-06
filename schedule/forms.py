from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone

from roll.models import RosterEntry

from .models import Assignment, Attendance, Event

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
            "ask_attendance",
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


class AssignmentForm(forms.ModelForm):
    class Meta:
        model = Assignment
        fields = ["member", "role"]
        widgets = {"role": forms.TextInput(attrs={"placeholder": "役割(例: カメラ)"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["member"].queryset = RosterEntry.objects.filter(is_member=True)
        self.fields["member"].empty_label = "部員を選択"


AssignmentFormSet = inlineformset_factory(
    Event,
    Assignment,
    form=AssignmentForm,
    extra=3,
    can_delete=True,
)


class AttendanceForm(forms.Form):
    status = forms.ChoiceField(
        label="出欠",
        choices=Attendance.Status.choices,
        widget=forms.RadioSelect,
    )
    comment = forms.CharField(
        label="コメント",
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "遅刻・早退など(任意)"}),
    )
