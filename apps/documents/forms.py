from django import forms

from .extraction import MAX_BYTES
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
            if isinstance(field.widget, forms.CheckboxInput):
                css = "form-check-input"
            field.widget.attrs.setdefault("class", css)

    def _get_validation_exclusions(self):
        # Контрольную сумму ИНН из модели форма не проверяет — это делает сверка (INN_INVALID)
        return super()._get_validation_exclusions() | {"inn"}


class UploadForm(forms.Form):
    file = forms.FileField(label="PDF или скан (PNG/JPEG)", widget=forms.ClearableFileInput(
        attrs={"class": "form-control", "accept": ".pdf,.png,.jpg,.jpeg"}))

    def clean_file(self):
        file = self.cleaned_data["file"]
        if file.size > MAX_BYTES or not file.size:
            raise forms.ValidationError("Загрузите файл размером от 1 байта до 6 МБ")
        if not file.name.lower().endswith((".pdf", ".png", ".jpg", ".jpeg")):
            raise forms.ValidationError("Поддерживаются PDF, PNG и JPEG")
        return file


class ConfirmDocumentForm(DocumentForm):
    confirmed = forms.BooleanField(label="Я сверил реквизиты с оригиналом и подтверждаю выбранные значения")


class SignatureForm(forms.Form):
    signature = forms.FileField(label="Отдельная подпись (.sig, .p7s)", widget=forms.ClearableFileInput(
        attrs={"class": "form-control", "accept": ".sig,.p7s,.p7m"}))

    def clean_signature(self):
        file = self.cleaned_data["signature"]
        if not 0 < file.size <= 2 * 1024 * 1024:
            raise forms.ValidationError("Допускается подпись размером до 2 МБ")
        return file
