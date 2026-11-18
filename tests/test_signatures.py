from pathlib import Path
from subprocess import CompletedProcess

import pytest

from apps.documents.signatures import _der_content, verify_cms, verify_pdf


def test_der_padding_does_not_remove_real_zero():
    assert _der_content(b'\x30\x03\x01\x02\x00\x00\x00') == b'\x30\x03\x01\x02\x00'
    with pytest.raises(ValueError):
        _der_content(b'\x30\x01\x01\x01')
    assert _der_content(b'\x30\x80\x00\x00\x00') == b'\x30\x80\x00\x00'
    with pytest.raises(ValueError):
        _der_content(b'\x30\x80\x04\x01\x00')


@pytest.mark.parametrize('error,status', [(b'content verify error', 'invalid'),
                                        (b'unsupported algorithm', 'unknown')])
def test_failure_is_not_success(monkeypatch, error, status):
    monkeypatch.setattr('apps.documents.signatures._command',
                        lambda args, **kw: CompletedProcess(args, 4, stdout=b'', stderr=error))
    result = verify_cms(b'original', b'signature')
    assert result['integrity'] == status and result['trust'] == 'not_checked'


def test_verified_content_must_match_input(monkeypatch):
    def run(args, **kwargs):
        Path(args[args.index('-out') + 1]).write_bytes(b'other content')
        return CompletedProcess(args, 0, stdout=b'', stderr=b'')
    monkeypatch.setattr('apps.documents.signatures._command', run)
    assert verify_cms(b'original', b'signature')['integrity'] == 'invalid'


def test_integrity_not_confused_with_certificate_trust(monkeypatch, settings):
    settings.SIGNATURE_TRUST_BUNDLE = ''
    def run(args, **kwargs):
        if args[0] == 'cms':
            Path(args[args.index('-out') + 1]).write_bytes(b'original')
            Path(args[args.index('-signer') + 1]).write_bytes(b'certificate')
        return CompletedProcess(args, 0, stdout=b'subject=Test', stderr=b'')
    monkeypatch.setattr('apps.documents.signatures._command', run)
    result = verify_cms(b'original', b'signature')
    assert result['integrity'] == 'valid' and result['trust'] == 'not_checked'
    assert result['revocation'] == 'not_checked'


def test_missing_tool_is_unknown(monkeypatch):
    def missing(args, **kwargs):
        raise FileNotFoundError
    monkeypatch.setattr('apps.documents.signatures._command', missing)
    assert verify_cms(b'original', b'signature')['integrity'] == 'unknown'


def test_malformed_pdf_is_not_valid_signature():
    assert verify_pdf(b'not pdf')[0]['integrity'] == 'unknown'


@pytest.mark.django_db
def test_invalid_signature_affects_result():
    from apps.documents.verification import verify_document
    from tests.test_verification import make_doc

    doc = make_doc()
    doc.processing = {'signature_checks': [{'results': [{'integrity': 'invalid'}]}]}
    result = verify_document(doc)
    assert result.verdict == 'error' and 'SIGNATURE_INVALID' in [i['code'] for i in result.issues]


@pytest.mark.django_db
@pytest.mark.parametrize('name,code', [('Тестов Иван Иванович', 'CERTIFICATE_SIGNER_MISMATCH'),
                                     ('Образцов Пётр Сергеевич', None)])
def test_certificate_identity_bound_to_document_signer(name, code):
    from apps.documents.verification import verify_document
    from tests.test_verification import make_doc

    doc = make_doc()
    doc.processing = {'signature_checks': [{'results': [{'integrity': 'valid', 'trust': 'verified',
                        'revocation': 'verified', 'identities': [{'name': name}]}]}]}
    codes = [i['code'] for i in verify_document(doc).issues]
    if code:
        assert code in codes
    else:
        assert not codes
