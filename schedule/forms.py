from django import forms
from django.db.models import Q
from django.forms import inlineformset_factory
from django.utils import timezone

from equipment.models import Equipment
from places.models import Place
from roll.models import RosterEntry

from .models import Assignment, Attendance, Event, EventEquipment

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
            "place",
            "description",
            "recurrence",
            "recurrence_until",
            "ask_attendance",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 予定の場所として使える場所。すでに選ばれている場所は、あとから外れても選択肢に残す
        venues = Q(is_active=True, is_venue=True)
        if self.instance.pk and self.instance.place_id:
            venues |= Q(pk=self.instance.place_id)
        self.fields["place"].queryset = Place.objects.filter(venues).select_related("parent")
        self.fields["place"].empty_label = "場所なし・未定"
        self.fields["place"].required = False

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


class AssignmentSelection:
    """名簿の表で選ばれた割当部員(チェックと役割)を、POST から読み取って検証・保存する。

    表は ``assign_member``(チェックされた名簿の id。複数)と ``role_<id>``(役割)で送られてくる。
    新しく選べるのは放送部員だけ。すでに割り当てた人は、部員でなくなっていても残せる。
    """

    ROLE_MAX_LENGTH = Assignment._meta.get_field("role").max_length

    def __init__(self, data, event):
        self.event = event
        self.errors = []
        self.selection = {}  # {名簿の id: 役割}
        self._existing = (
            set(event.assignments.values_list("member_id", flat=True)) if event.pk else set()
        )

        raw_ids = data.getlist("assign_member") if hasattr(data, "getlist") else []
        ids = []
        for raw in raw_ids:
            if str(raw).isdigit() and int(raw) not in ids:
                ids.append(int(raw))

        found = {entry.pk: entry for entry in RosterEntry.objects.filter(pk__in=ids)}
        for pk in ids:
            entry = found.get(pk)
            if entry is None:
                self.errors.append("名簿にない部員が選ばれています。")
                continue
            if not entry.is_member and pk not in self._existing:
                self.errors.append(f"{entry.name} さんは放送部員ではないため、割り当てられません。")
                continue
            role = (data.get(f"role_{pk}") or "").strip()
            if len(role) > self.ROLE_MAX_LENGTH:
                self.errors.append(
                    f"{entry.name} さんの役割は{self.ROLE_MAX_LENGTH}文字以内にしてください。"
                )
                continue
            self.selection[pk] = role

    def is_valid(self):
        return not self.errors

    def save(self, event):
        """選ばれていない人の割当を外し、選ばれた人の割当と役割を保存する。"""
        event.assignments.exclude(member_id__in=self.selection).delete()
        for member_id, role in self.selection.items():
            Assignment.objects.update_or_create(
                event=event, member_id=member_id, defaults={"role": role}
            )


class EventEquipmentForm(forms.ModelForm):
    class Meta:
        model = EventEquipment
        fields = ["equipment", "quantity"]
        widgets = {"quantity": forms.NumberInput(attrs={"min": 1, "placeholder": "数量"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["equipment"].queryset = Equipment.objects.filter(is_active=True)
        self.fields["equipment"].empty_label = "機材を選択"


EventEquipmentFormSet = inlineformset_factory(
    Event,
    EventEquipment,
    form=EventEquipmentForm,
    extra=2,
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
