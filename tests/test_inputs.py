import pytest
from wazo_dird_optimogo.inputs import (
    should_skip_number, normalize_number_key, validate_term, normalize_term_key,
)


@pytest.mark.parametrize('raw', [None, '', '  ', 'anonymous', 'Anonymous', 'unknown',
                                 'private', 'withheld', 'restricted', 'abc', '++'])
def test_skip_non_dialable(raw):
    assert should_skip_number(raw) is True


@pytest.mark.parametrize('raw', ['+61399999999', '0399999999', '  04 1234 5678 '])
def test_do_not_skip_dialable(raw):
    assert should_skip_number(raw) is False


def test_number_key_strips_punctuation_keeps_plus():
    assert normalize_number_key('+61 3 9999-9999') == '+61399999999'
    assert normalize_number_key('(03) 9999 9999') == '0399999999'


def test_validate_term_length_bounds():
    assert validate_term('ab', 3, 64) is None          # too short
    assert validate_term('x' * 65, 3, 64) is None       # too long
    assert validate_term('  ace  ', 3, 64) == 'ace'     # trimmed, ok
    assert validate_term(None, 3, 64) is None


def test_term_key_normalizes_whitespace_and_case():
    assert normalize_term_key('  Acme   Plumbing ') == 'acme plumbing'
