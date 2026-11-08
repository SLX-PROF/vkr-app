"""Понятное представление отдельных проверок для карточки и PDF."""
from uuid import UUID

FNS_URL = "https://pb.nalog.ru/"
CBR_URL = "https://www.cbr.ru/inside/warning-list/"


def counterparty_requests(sources):
    """Документы для уточнения сведений; их запрос не меняет оценку риска."""
    sources = list(sources)
    rows = [
        {"title": "Полномочия подписанта", "text": "Документ о назначении руководителя; если подписывает "
         "представитель — доверенность или МЧД с перечнем полномочий и сроком действия. "
         "Для электронной МЧД — исходный XML и электронная подпись."},
        {"title": "Сведения банка", "text": "Имеющиеся уведомления банка о категории ЗСК, ограничениях "
         "и отказах с датами, а также документы об их пересмотре. Если уведомлений нет — сообщить об этом. "
         "Ответ контрагента требует проверки и не устанавливает категорию ЦБ автоматически."},
    ]
    for source in sources:
        data = source.data if source.status == "success" else {}
        if source.source_name == "ФССП" and (not data or data.get("candidate_records")
                                             or data.get("active_proceedings") is None
                                             or data.get("total_debt")):
            rows.append({"title": "Исполнительные производства", "text": "Пояснения по найденным записям, "
                         "принадлежности организации и текущему состоянию задолженности; "
                         "при погашении — подтверждающие документы и постановления об окончании производства."})
        elif source.source_name == "ЕФРСБ" and (not data or data.get("messages")
                                               or data.get("unavailable_fields")):
            rows.append({"title": "Публикации о банкротстве", "text": "Пояснения по опубликованным сообщениям "
                         "и документы о текущем состоянии или завершении соответствующих процедур."})
        elif source.source_name == "КАД Арбитр" and (not data or data.get("records")
                                                   or data.get("unavailable_fields")):
            rows.append({"title": "Арбитражные споры", "text": "Пояснения по существенным спорам, копии "
                         "итоговых судебных актов и документы об исполнении обязательств."})
        elif source.source_name == "Прозрачный бизнес" and any(data.get(key) is True for key in (
                "unreliable_address", "unreliable_director", "unreliable_details")):
            rows.append({"title": "Отметки о недостоверности", "text": "Пояснения по отметкам ФНС об адресе "
                         "или руководителе и документы об исправлении сведений в ЕГРЮЛ."})
    return rows


def source_observations(sources):
    rows = []
    pb = next((s.data for s in sources if s.source_name == "Прозрачный бизнес" and s.status == "success"), {})
    for key, title in (("unreliable_address", "Недостоверность адреса"),
                       ("unreliable_director", "Недостоверность сведений о руководителе")):
        value = pb.get(key)
        rows.append({"title": title, "text": "Есть отметка ФНС" if value is True else
                     "Отметка ФНС не выявлена" if value is False else "Нет достаточных данных",
                     "details": "; ".join(pb.get(key + "_notes", [])), "url": FNS_URL})
    cbr = next((s.data for s in sources if s.source_name == "ЦБ: нелегальная деятельность"
                and s.status == "success"), {})
    value = cbr.get("found_by_inn")
    rows.append({"title": "Перечень нелегальной финансовой деятельности ЦБ",
                 "text": "Найдено точное совпадение ИНН" if value is True else
                 "Совпадений по ИНН не найдено" if value is False else "Нет достаточных данных",
                 "details": cbr.get("limitation", ""), "url": CBR_URL})
    for source in sources:
        if source.status != "success" or not source.data.get("provider"):
            continue
        data = source.data
        title, text = source.source_name, ""
        if source.source_name == "ФССП":
            debt = data.get("total_debt")
            text = (f"Подтверждённый остаток задолженности: {debt:,.2f} руб." if debt is not None else
                    f"Подтверждено не менее {data.get('confirmed_debt_lower_bound', 0):,.2f} руб.; итог не установлен")
            text += f". Записей для уточнения: {len(data.get('candidate_records', []))}"
        elif source.source_name == "ЕФРСБ":
            messages = data.get("messages", [])
            text = f"Опубликованных сообщений в ответе поставщика: {len(messages)}"
        elif source.source_name == "КАД Арбитр":
            count = data.get("cases_last_year")
            text = (f"Дел за период: {count}" if count is not None else
                    f"Подтверждено не менее {data.get('confirmed_cases_lower_bound', 0)} дел; итог не установлен")
            text += f" ({data.get('period_start')} — {data.get('period_end')})"
        if text:
            rows.append({"title": title, "text": text.replace(",", " "),
                         "details": f"Поставщик: {data['provider']}. {data.get('limitation', '')}",
                         "url": data["primary_url"]})
    return rows


def source_evidence(sources):
    """Показывает основания вывода; неподтверждённые кандидаты выделяются явно."""
    blocks = []
    for source in sources:
        if source.status != "success" or not source.data.get("provider"):
            continue
        data = source.data
        records = []
        if source.source_name == "ЕФРСБ":
            for row in data.get("messages", []):
                records.append({"title": row.get("Тип") or "Тип сообщения не указан",
                                "text": f"Публикация: {row.get('Дата') or 'нет даты'}. "
                                        f"Дело: {row.get('Дело') or 'не указано'}", "url": ""})
        elif source.source_name == "ФССП":
            for key, label in (("records", "Совпали наименование и адрес"),
                               ("candidate_records", "Принадлежность требует проверки")):
                for row in data.get(key, []):
                    records.append({"title": row.get("ИспПрНомер") or "Номер не указан",
                                    "text": f"{label}. {row.get('ДолжНаим') or ''}. {row.get('ДолжАдрес') or ''}. "
                                            f"Дата возбуждения: {row.get('ИспПрДата') or 'не указана'}. "
                                            f"Остаток: {row.get('ОстЗадолж', 'нет данных')}", "url": ""})
        elif source.source_name == "КАД Арбитр":
            for key, label in (("records", "ИНН и период подтверждены"),
                               ("candidate_records", "Сопоставление требует проверки")):
                for row in data.get(key, []):
                    try:
                        url = "https://kad.arbitr.ru/Card/" + str(UUID(str(row.get("UUID"))))
                    except ValueError:
                        url = ""
                    records.append({"title": row.get("Номер") or "Номер дела не указан",
                                    "text": f"{label}. Дата: {row.get('Дата') or 'не указана'}. "
                                            f"Суд: {row.get('Суд') or 'не указан'}. "
                                            f"Сумма иска: {row.get('СуммИск', 'нет данных')}", "url": url})
        if records:
            blocks.append({"title": source.source_name, "total": len(records), "rows": records[:30]})
    return blocks
