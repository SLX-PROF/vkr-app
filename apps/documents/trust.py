"""Обновление CRL по фиксированным адресам с проверкой подписи и срока действия."""
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests
from asn1crypto import crl, pem
from django.conf import settings

from .signatures import _command

ANCHORS = Path(__file__).with_name("trust_anchors")
ROOT_SHA256 = "4bb37cc7c0ff4bf2aa893e95076ebb3565c69237ee1b61635beee4c1966495c7"
INTERMEDIATE_SHA256 = "999870011a6fd29fc6338af2c7dab496159e09377cdf2126ab3e604323afce21"
SOURCES = (
    ("http://crl.gosuslugi.ru/cdp/guc2022.crl", "guc2022.pem"),
    ("http://crl.roskazna.ru/crl/ucfk_2025.crl", "treasury2025.pem"),
)


def _certificate(name, fingerprint):
    data = (ANCHORS / name).read_bytes()
    if hashlib.sha256(pem.unarmor(data)[2]).hexdigest() != fingerprint:
        raise ValueError("Не совпадает отпечаток установленного сертификата УЦ")
    return data


def _download(url):
    # HTTP допустим только для подписанного CRL. Перенаправления не разрешаются;
    # адреса из пользовательских сертификатов никогда не загружаются.
    with requests.get(url, stream=True, timeout=(5, 20), allow_redirects=False) as response:
        if response.status_code != 200:
            raise ValueError(f"Список отзыва недоступен: HTTP {response.status_code}")
        chunks, length = [], 0
        for chunk in response.iter_content(65536):
            length += len(chunk)
            if length > 32 * 1024 * 1024:
                raise ValueError("Превышен размер списка отзыва")
            chunks.append(chunk)
        return b"".join(chunks)


def refresh_trust_bundle(destination):
    """Публикует новый набор атомарно, только после проверки обоих CRL."""
    destination = Path(destination)
    root = _certificate("guc2022.pem", ROOT_SHA256)
    _certificate("treasury2025.pem", INTERMEDIATE_SHA256)
    now = datetime.now(timezone.utc)
    records, bundle = [], root
    with tempfile.TemporaryDirectory(prefix="vkr-crl-") as temporary:
        temporary = Path(temporary)
        environment = os.environ.copy()
        if settings.SIGNATURE_OPENSSL_ENGINE:
            configuration = temporary / "openssl.cnf"
            configuration.write_text(
                "openssl_conf = openssl_init\n[openssl_init]\nengines = engines\n[engines]\n"
                "gost = gost\n[gost]\nengine_id = gost\n"
                f"dynamic_path = {settings.SIGNATURE_OPENSSL_ENGINE}\n"
                "default_algorithms = ALL\ninit = 1\n", encoding="utf-8")
            environment["OPENSSL_CONF"] = str(configuration)
        checked = _command(["verify", "-CAfile", str(ANCHORS / "guc2022.pem"),
                            "-no-CApath", "-no-CAstore", str(ANCHORS / "treasury2025.pem")],
                           timeout=15, env=environment)
        if checked.returncode:
            raise ValueError("Не подтверждена цепочка установленного промежуточного УЦ")
        for url, issuer in SOURCES:
            data = _download(url)
            parsed = crl.CertificateList.load(data)
            dates = parsed["tbs_cert_list"]
            issued, expires = dates["this_update"].native, dates["next_update"].native
            if not expires or not issued <= now < expires:
                raise ValueError("Список отзыва просрочен либо ещё не действует")
            path = temporary / "current.crl"
            path.write_bytes(data)
            checked = _command(["crl", "-in", str(path), "-inform", "DER", "-noout",
                                "-verify", "-CAfile", str(ANCHORS / issuer)], timeout=15, env=environment)
            if checked.returncode or b"verify OK" not in checked.stderr:
                raise ValueError("Не подтверждена подпись списка отзыва")
            bundle += pem.armor("X509 CRL", data)
            records.append({"url": url, "sha256": hashlib.sha256(data).hexdigest(),
                            "this_update": issued.isoformat(), "next_update": expires.isoformat()})
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, staging = tempfile.mkstemp(prefix=".trust-", dir=destination.parent)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(bundle)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(staging, 0o644)
            os.replace(staging, destination)
        finally:
            Path(staging).unlink(missing_ok=True)
    report = {"updated_at": now.isoformat(), "root_sha256": ROOT_SHA256, "crls": records}
    destination.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
