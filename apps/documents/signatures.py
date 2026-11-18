"""Проверка соответствия CMS-подписи байтам документа. Доверие к УЦ проверяется отдельно."""
import hashlib
import re
import subprocess
import tempfile
import time
from io import BytesIO
from pathlib import Path

from asn1crypto import pem, x509
from asn1crypto.parser import peek
from django.conf import settings
from pypdf import PdfReader


def _command(args, *, timeout=15, env=None):
    return subprocess.run([settings.SIGNATURE_OPENSSL, *args], capture_output=True, timeout=timeout, env=env)


def certificate_identities(data):
    """Идентификаторы только сертификатов подписантов, выбранных OpenSSL CMS."""
    identities = []
    for block in re.findall(rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", data, re.S):
        certificate = x509.Certificate.load(pem.unarmor(block)[2])
        attributes = {}
        for rdn in certificate.subject.chosen:
            for attribute in rdn:
                attributes[attribute['type'].dotted] = str(attribute['value'].native)
        name = " ".join(filter(None, (attributes.get('2.5.4.4'), attributes.get('2.5.4.42'))))
        identities.append({"name": name, "common_name": attributes.get('2.5.4.3', ''),
                           "organization_inn": attributes.get('1.2.643.100.4', ''),
                           "ogrn": attributes.get('1.2.643.100.1', ''),
                           "sha256": hashlib.sha256(certificate.dump()).hexdigest()})
    return identities


def verify_cms(content, signature, *, deadline=None):
    """Не отключает проверку подписанных атрибутов или хеша содержимого."""
    result = {"integrity": "unknown", "trust": "not_checked", "revocation": "not_checked",
              "content_sha256": hashlib.sha256(content).hexdigest(), "certificate": ""}
    deadline = deadline or time.monotonic() + 30

    def command(args):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(args, 30)
        return _command(args, timeout=min(10, remaining))
    if not signature or len(signature) > 2 * 1024 * 1024:
        return {**result, "message": "Файл подписи пуст или превышает 2 МБ"}
    with tempfile.TemporaryDirectory(prefix="vkr-signature-") as directory:
        root = Path(directory)
        original, signed, verified, cert = [root / name for name in ("original", "signature", "verified", "signer.pem")]
        original.write_bytes(content)
        signed.write_bytes(signature)
        fmt = "PEM" if signature.lstrip().startswith(b"-----BEGIN") else "DER"
        args = ["cms", "-verify", "-binary", "-inform", fmt, "-in", str(signed), "-content", str(original),
                "-noverify", "-out", str(verified), "-signer", str(cert)]
        if settings.SIGNATURE_OPENSSL_ENGINE:
            args += ["-engine", settings.SIGNATURE_OPENSSL_ENGINE]
        try:
            response = command(args)
            if response.returncode:
                error = response.stderr.decode(errors="replace").lower()
                # Отсутствующий алгоритм не означает, что документ подделан.
                result["integrity"] = "unknown" if any(x in error for x in (
                    "unsupported", "unknown digest", "invalid engine", "could not load")) else "invalid"
                result["message"] = ("Алгоритм подписи не поддерживается настроенным криптографическим средством"
                                     if result["integrity"] == "unknown" else
                                     "Подпись не соответствует документу либо имеет некорректный формат")
                return result
            if (not verified.exists()
                    or hashlib.sha256(verified.read_bytes()).digest() != hashlib.sha256(content).digest()):
                return {**result, "integrity": "invalid", "message": "Подписано другое содержимое"}
            result["integrity"] = "valid"
            result["message"] = "Криптографическая подпись соответствует байтам документа"
            info = command(["x509", "-in", str(cert), "-noout", "-subject", "-issuer", "-serial", "-dates",
                             "-nameopt", "utf8"])
            if info.returncode == 0:
                result["certificate"] = info.stdout.decode("utf-8", errors="replace")[:8000]
            try:
                result["identities"] = certificate_identities(cert.read_bytes())
            except (ValueError, KeyError, TypeError):
                result["identities"] = []
            bundle = settings.SIGNATURE_TRUST_BUNDLE
            if bundle:
                # Пользовательские сертификаты из файла подписи не становятся доверенными корнями.
                checked = command([x for x in args if x != "-noverify"] + [
                    "-CAfile", bundle, "-no-CApath", "-no-CAstore", "-purpose", "any", "-crl_check_all"])
                if checked.returncode == 0:
                    result.update(trust="verified", revocation="verified")
                else:
                    error = checked.stderr.decode(errors="replace").lower()
                    if "certificate revoked" in error:
                        result.update(trust="failed", revocation="revoked")
                    elif "certificate has expired" in error or "not yet valid" in error:
                        result["trust"] = "failed"
                    else:
                        result["trust"] = "unknown"
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            result["message"] = "Криптографическая проверка недоступна или превысила лимит времени"
    return result


def _der_content(data):
    """Отделяет заполнение по длине ASN.1 BER/DER, сохраняя исходную кодировку CMS."""
    if len(data) < 2 or data[0] != 0x30:
        raise ValueError("Неизвестный формат CMS")
    size = peek(data)
    if size > len(data) or any(data[size:]):
        raise ValueError("Неверное заполнение CMS")
    return data[:size]


def pdf_signature_parts(content):
    """Проверяет, что исключён только токен /Contents, а остальной диапазон непрерывен."""
    reader = PdfReader(BytesIO(content))
    signatures = []
    for field in (reader.get_fields() or {}).values():
        if field.get("/FT") != "/Sig" or not field.get("/V"):
            continue
        signature = field["/V"].get_object()
        if signature.get("/SubFilter") not in ("/adbe.pkcs7.detached", "/ETSI.CAdES.detached"):
            raise ValueError("Формат встроенной подписи не поддерживается")
        byte_range = signature.get("/ByteRange")
        if (not isinstance(byte_range, list) or len(byte_range) != 4
                or any(not isinstance(n, int) or isinstance(n, bool) for n in byte_range)):
            raise ValueError("Некорректные диапазоны подписи")
        start, length, second, tail = byte_range
        if start != 0 or length <= 0 or second <= length or tail < 0 or second + tail > len(content):
            raise ValueError("Некорректное покрытие документа")
        gap = content[length:second]
        if not re.fullmatch(rb"<[0-9a-fA-F\s]+>", gap):
            raise ValueError("За пределами подписи находятся посторонние данные")
        decoded = bytes.fromhex(re.sub(rb"\s", b"", gap[1:-1]).decode("ascii"))
        value = signature.get("/Contents")
        value = value.original_bytes if hasattr(value, "original_bytes") else bytes(value)
        if decoded != value:
            raise ValueError("Содержимое подписи не соответствует диапазонам")
        signatures.append((content[:length] + content[second:second + tail], _der_content(decoded),
                           second + tail == len(content)))
        if len(signatures) > 8:
            raise ValueError("Слишком много встроенных подписей")
    return signatures


def verify_pdf(content):
    deadline = time.monotonic() + 35
    try:
        parts = pdf_signature_parts(content)
    except Exception:
        return [{"integrity": "unknown", "trust": "not_checked", "revocation": "not_checked",
                 "message": "Встроенные подписи не удалось безопасно разобрать"}]
    results = []
    for data, signature, full in parts:
        result = verify_cms(data, signature, deadline=deadline)
        result["covers_current_file"] = full
        if not full:
            result["message"] += ". После подписанной редакции в PDF добавлены данные; требуется проверка изменений"
        results.append(result)
    return results
