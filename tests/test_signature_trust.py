from datetime import datetime, timedelta, timezone
from subprocess import CompletedProcess

import pytest

from apps.documents import trust


def test_installed_anchor_fingerprints():
    assert trust._certificate('guc2022.pem', trust.ROOT_SHA256)
    assert trust._certificate('treasury2025.pem', trust.INTERMEDIATE_SHA256)
    with pytest.raises(ValueError):
        trust._certificate('guc2022.pem', '0' * 64)


@pytest.mark.parametrize('failure', ['expired', 'signature', 'network', None])
def test_refresh_keeps_previous_bundle_on_failure(tmp_path, monkeypatch, failure):
    now = datetime.now(timezone.utc)
    class Date:
        def __init__(self, value):
            self.native = value
    dates = {'this_update': Date(now - timedelta(days=1)),
             'next_update': Date(now + timedelta(days=-1 if failure == 'expired' else 1))}
    monkeypatch.setattr(trust.crl.CertificateList, 'load', lambda data: {'tbs_cert_list': dates})
    def download(url):
        if failure == 'network':
            raise OSError('Unavailable')
        return b'CRL'
    monkeypatch.setattr(trust, '_download', download)
    monkeypatch.setattr(trust, '_command', lambda args, **kw: CompletedProcess(
        args, 1 if failure == 'signature' and args[0] == 'crl' else 0, stderr=b'verify OK'))
    destination = tmp_path / 'government.pem'
    destination.write_bytes(b'previous bundle')
    if failure:
        with pytest.raises((ValueError, OSError)):
            trust.refresh_trust_bundle(destination)
        assert destination.read_bytes() == b'previous bundle'
    else:
        report = trust.refresh_trust_bundle(destination)
        assert len(report['crls']) == 2
        assert destination.read_bytes().count(b'BEGIN X509 CRL') == 2
        assert destination.with_suffix('.json').exists()
