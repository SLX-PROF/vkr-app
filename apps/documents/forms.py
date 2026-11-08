from django import forms

from .models import PrimaryDocument


class DocumentForm(forms.ModelForm):
    # ИНН и реквизиты намеренно не проверяются формой: их отсутствие и ошибки — результат сверки, а не отказ формы.
    inn = forms.CharField(label="ИНН контрагента", max_length=12, required=False)

    class Meta:
        model = PrimaryDocument
        fields = ["doc_type", "number", "date", "inn", "amount", "signer_name", "signer_position"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("number", "amount", "signer_name", "signer_position"):
            self.fields[name].required = False
        for field in self.fields.values():
            css = "form-select" if isinstance(field, forms.ChoiceField) else "form-control"
            field.widget.attrs.setdefault("class", css)

    def _get_validation_exclusions(self):
        # Контрольную сумму ИНН из модели форма не проверяет — это делает сверка (INN_INVALID)
        return super()._get_validation_exclusions() | {"inn"}
