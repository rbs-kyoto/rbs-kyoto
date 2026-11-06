from django import forms

from .models import Place


class PlaceForm(forms.ModelForm):
    class Meta:
        model = Place
        fields = [
            "name",
            "code",
            "parent",
            "is_venue",
            "is_storage",
            "description",
            "notes",
            "is_active",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        parents = Place.objects.filter(is_active=True)
        if self.instance.pk:
            parents = parents.exclude(pk=self.instance.pk)
        self.fields["parent"].queryset = parents
        self.fields["parent"].required = False

    def clean_parent(self):
        parent = self.cleaned_data["parent"]
        ancestor = parent
        while ancestor:
            if self.instance.pk and ancestor.pk == self.instance.pk:
                raise forms.ValidationError("自分自身や、自分の下にある場所を上位の場所には指定できません。")
            ancestor = ancestor.parent
        return parent
