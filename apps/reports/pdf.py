"""PDF по сохранённому сеансу проверки; внешние источники повторно не опрашиваются."""
from io import BytesIO
from xml.sax.saxutils import escape

from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .observations import counterparty_requests, source_evidence, source_observations


def build_report(session, *, show_details: bool) -> bytes:
    """Детальные факторы включаются только при наличии права доступа у получателя."""
    fonts = settings.BASE_DIR / "static" / "fonts"
    for name, filename in [("Noto", "NotoSans-Regular.ttf"), ("Noto-Bold", "NotoSans-Bold.ttf")]:
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(fonts / filename)))
    pdfmetrics.registerFontFamily("Noto", normal="Noto", bold="Noto-Bold")
    body = ParagraphStyle("ReportBody", fontName="Noto", fontSize=9, leading=13, spaceAfter=6)
    title = ParagraphStyle("ReportTitle", parent=body, fontName="Noto-Bold", fontSize=15, leading=20)
    heading = ParagraphStyle("ReportHeading", parent=body, fontName="Noto-Bold", fontSize=11, spaceBefore=10)
    cell = ParagraphStyle("ReportCell", parent=body, fontSize=8, leading=11)

    def p(text, style=body):
        return Paragraph(escape(str(text)), style)

    sources = list(session.sources.all().order_by("pk"))
    registry = next((s.data for s in sources if s.source_name == "ЕГРЮЛ" and s.status == "success"), {})
    name = (registry.get("short_name") or registry.get("full_name")
            or session.contractor.short_name or session.contractor.inn)
    story = [p("Отчёт о проверке контрагента", title), p(f"Сеанс № {session.pk}"), p(name, heading)]
    ogrn = registry.get("ogrn") or session.contractor.ogrn or "нет данных"
    story += [p(f"ИНН: {session.contractor.inn}"), p(f"ОГРН: {ogrn}")]
    if not registry:
        story.append(p("Реквизиты приведены из текущей карточки; ответ ЕГРЮЛ для этого сеанса отсутствует."))
    story += [p(f"Дата проверки: {timezone.localtime(session.started_at):%d.%m.%Y %H:%M:%S}"),
              p(f"Инициатор: {session.initiator.get_username() if session.initiator else 'не указан / удалён'}"),
              p(f"Результат: {session.get_status_display()}, {session.score} из 100 баллов", heading)]
    if session.is_demo or any(s.mode == "mock" for s in sources):
        story.append(p("ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ. Результат не является проверкой реальной организации.", heading))
    if session.is_partial or not sources:
        story.append(p("Частичная проверка: отсутствие данных не означает отсутствие риска.", heading))
    if any(s.mode == "unknown" for s in sources) or not sources:
        story.append(p("Режим источников для части данных не сохранён. Происхождение результата требует уточнения."))
    if show_details:
        story.append(p("Результаты по источникам", heading))
        for row in source_observations(sources):
            story.append(p(f"{row['title']}: {row['text']}. {row['details']}"))
        for block in source_evidence(sources):
            story.append(p(f"{block['title']}: показано {len(block['rows'])} из {block['total']} записей", heading))
            for row in block["rows"]:
                story.append(p(f"{row['title']}. {row['text']}"))
        story.append(p("Индекс риска системы не является оценкой ЗСК. Категория ЗСК и банковские отказы "
                       "764/639/550 в этом сеансе не установлены."))
        story.append(p("Выявленные факторы", heading))
        for factor in session.factors:
            story.append(p(f"+{factor['points']} — {factor['text']} (источник: {factor.get('source') or 'не указан'})"))
        if not session.factors:
            story.append(p("По полученным данным правила риска не сработали."))
        story.append(p("Что запросить у контрагента", heading))
        for row in counterparty_requests(sources):
            story.append(p(f"{row['title']}: {row['text']}"))
        story.append(p("Полученные документы проверяет сотрудник. Сам запрос не изменяет оценку риска."))
    else:
        story.append(p("Детальные факторы доступны сотрудникам СБ, юристам и администратору."))
    story.append(p("Использованные источники", heading))
    rows = [[p(x, cell) for x in ("Источник", "Состояние", "Режим", "Время, с")]]
    mode_labels = {"mock": "демо", "api": "API", "web": "веб", "unknown": "не сохранён"}
    for source in sources:
        status = source.get_status_display()
        if source.status != "success":
            status += ": данные не получены"
        elif source.data.get("unavailable_fields"):
            status = "Получены не все показатели"
        rows.append([p(source.source_name, cell), p(status, cell), p(mode_labels.get(source.mode, source.mode), cell),
                     p(f"{source.elapsed:.3f}", cell)])
    if len(rows) == 1:
        rows.append([p("История источников отсутствует", cell), p("—", cell), p("—", cell), p("—", cell)])
    table = Table(rows, colWidths=[48*mm, 62*mm, 30*mm, 25*mm], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [table, Spacer(1, 4*mm)]
    story.append(p("Баллы отражают сработавшие правила и не являются вероятностью нарушения. "
                   "Решение о сотрудничестве принимает сотрудник."))
    if not session.scoring_config:
        story.append(p("Параметры оценки для этого архивного сеанса не сохранены."))
    output = BytesIO()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Noto", 8)
        canvas.drawCentredString(105*mm, 12*mm, f"ООО «Валдэкс» · Страница {doc.page}")
        canvas.restoreState()

    SimpleDocTemplate(output, pagesize=(210*mm, 297*mm), leftMargin=22*mm, rightMargin=22*mm,
                      topMargin=18*mm, bottomMargin=22*mm, title="Отчёт о проверке контрагента",
                      author="Система проверки контрагентов").build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
