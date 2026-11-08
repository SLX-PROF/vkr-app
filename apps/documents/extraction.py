"""Извлечение реквизитов PDF/изображения. Распознанные значения требуют подтверждения."""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import warnings
from datetime import date
from pathlib import Path

from PIL import Image, ImageOps
from pypdf import PdfReader

from apps.core.validators import is_valid_inn

MAX_BYTES = 6 * 1024 * 1024
MAX_PAGES = 20
MAX_OCR_PAGES = 3


class ExtractionError(ValueError):
    """Не удалось безопасно обработать файл."""


def extract_fields(text, *, ocr=False):
    """Не выбирает произвольно один ИНН, если документ содержит несколько сторон."""
    fields, notes = {}, []
    label = r"(?:ИНН|INN|[ИIU][НH]{2})" if ocr else r"(?:ИНН|INN)"
    inns = list(dict.fromkeys(re.findall(label + r"(?:\s*/\s*КПП)?\s*[:№]?\s*(\d{10,12})(?!\d)", text, re.I)))
    inns = [n for n in inns if is_valid_inn(n)]
    if len(inns) == 1:
        fields["inn"] = inns[0]
    elif len(inns) > 1:
        notes.append("В документе несколько ИНН. Выберите ИНН проверяемого контрагента.")
    for pattern, kind in [(r"универсальн\w*\s+передаточн|\bУПД\b", "upd"),
                          (r"КС[-– ]?2\b", "ks2"), (r"КС[-– ]?3\b", "ks3"),
                          (r"ТОРГ[-– ]?12\b", "torg12"), (r"сч[её]т[- ]фактур", "vat_invoice"),
                          (r"сч[её]т\s*(?:на оплату|№)", "invoice")]:
        if re.search(pattern, text, re.I):
            fields["doc_type"] = kind
            break
    number = re.search(r"(?:№|Номер\s*[:])\s*([\w./-]{1,50})", text, re.I)
    if number:
        fields["number"] = number[1]
    dates = []
    for d, m, y in re.findall(r"\bот\s+(\d{2})[./](\d{2})[./](\d{4})\b", text, re.I):
        try:
            dates.append(date(int(y), int(m), int(d)).isoformat())
        except ValueError:
            pass
    dates = list(dict.fromkeys(dates))
    if len(dates) == 1:
        fields["date"] = dates[0]
    amounts = re.findall(r"(?:всего\s+к\s+оплате|итого\s+к\s+оплате|итого)\s*[:=]?\s*"
                         r"([\d \u00a0]+[,.]\d{2})(?!\d)", text, re.I)
    amounts = list(dict.fromkeys(re.sub(r"[\s\u00a0]", "", x).replace(",", ".") for x in amounts))
    if len(amounts) == 1:
        fields["amount"] = amounts[0]
    signer = re.search(r"([Гг]енеральный\s+директор|[Дд]иректор|[Пп]одписант|[Рр]уководитель)\s*[:]?\s*"
                       r"([А-ЯЁ][а-яё-]+\s+(?:[А-ЯЁ][а-яё-]+\s+[А-ЯЁ][а-яё-]+|[А-ЯЁ]\.\s*[А-ЯЁ]\.))", text)
    if signer:
        fields["signer_position"], fields["signer_name"] = signer[1].capitalize(), signer[2]
    notes.append("Проверьте все реквизиты по оригиналу: распознавание может содержать ошибки.")
    return fields, inns, notes


def _run(args, timeout=12):
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=True)
        return result.stdout.decode("utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise ExtractionError("Средства распознавания на сервере не установлены") from exc
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        raise ExtractionError("Распознавание не завершилось. Проверьте качество и размер файла") from exc


def _ocr(path):
    return _run(["tesseract", str(path), "stdout", "-l", "rus+eng", "--psm", "3"])[:60000]


def process_file(path):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ExtractionError("Максимальный размер файла — 6 МБ")
    with path.open("rb") as source:
        prefix = source.read(8)
    chunks, notes, methods = [], [], set()
    signatures, pages = 0, 1
    with tempfile.TemporaryDirectory(prefix="vkr-ocr-") as temporary:
        folder = Path(temporary)
        if prefix.startswith(b"%PDF-"):
            reader = PdfReader(path)
            if reader.is_encrypted:
                raise ExtractionError("PDF защищён паролем. Загрузите доступную для чтения копию")
            pages = len(reader.pages)
            if pages > MAX_PAGES:
                raise ExtractionError("Допускается не более 20 страниц PDF")
            signatures = sum(field.get("/FT") == "/Sig" for field in (reader.get_fields() or {}).values())
            ocr_count = 0
            for i, page in enumerate(reader.pages):
                contents = page.get_contents()
                if contents is not None and len(contents.get_data()) > 8 * 1024 * 1024:
                    raise ExtractionError("Слишком сложная страница PDF; разделите документ")
                text = (page.extract_text() or "")[:60000]
                if len(re.sub(r"\s", "", text)) < 20:
                    if ocr_count >= MAX_OCR_PAGES:
                        notes.append(f"Страница {i + 1} не распознана: за одну загрузку обрабатывается до 3 сканов.")
                        continue
                    image = folder / f"page-{i + 1}"
                    _run(["pdftoppm", "-f", str(i + 1), "-l", str(i + 1), "-scale-to", "2200",
                          "-png", "-singlefile", str(path), str(image)])
                    text = _ocr(image.with_suffix(".png"))
                    methods.add("ocr")
                    ocr_count += 1
                else:
                    methods.add("pdf_text")
                chunks.append(text)
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path) as image:
                    if image.format not in ("PNG", "JPEG") or image.width * image.height > 20000000:
                        raise ExtractionError("Загрузите PNG/JPEG не более 20 миллионов пикселей")
                    image = ImageOps.exif_transpose(image).convert("RGB")
                    image.save(folder / "image.png")
            chunks.append(_ocr(folder / "image.png"))
            methods.add("ocr")
    text = "\n".join(chunks)[:100000]
    if not text.strip():
        raise ExtractionError("Текст не обнаружен. Загрузите более чёткий файл или введите реквизиты вручную")
    fields, inns, field_notes = extract_fields(text, ocr="ocr" in methods)
    if signatures:
        notes.append("В PDF обнаружены поля электронной подписи. Их наличие не подтверждает действительность подписи.")
    return {"method": "+".join(sorted(methods)), "pages": pages, "fields": fields, "inn_candidates": inns,
            "notes": notes + field_notes, "text": text[:12000], "signature_fields": signatures,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def extract_file(path):
    """Отдельный процесс ограничивает время и память обработки PDF."""
    try:
        result = subprocess.run([sys.executable, "-m", "apps.documents.extraction", str(path)],
                                capture_output=True, timeout=45, check=True)
        payload = json.loads(result.stdout.decode("utf-8"))
    except (subprocess.SubprocessError, ValueError) as exc:
        raise ExtractionError("Файл не удалось обработать за отведённое время") from exc
    if "error" in payload:
        raise ExtractionError(payload["error"])
    return payload


if __name__ == "__main__":
    try:
        if sys.platform != "win32":
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (640 * 1024 * 1024, 640 * 1024 * 1024))
        output = process_file(sys.argv[1])
    except ExtractionError as error:
        output = {"error": str(error)}
    except Exception:
        output = {"error": "Файл повреждён или его формат не поддерживается"}
    print(json.dumps(output, ensure_ascii=True))
