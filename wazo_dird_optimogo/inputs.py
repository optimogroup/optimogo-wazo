_ANON_TOKENS = frozenset({
    '', 'anonymous', 'unknown', 'unavailable', 'private',
    'withheld', 'restricted', 'asserted', 'anonymous@anonymous.invalid',
})


def should_skip_number(raw):
    """True when there is no point querying OptimoGo (empty/anonymous/non-dialable)."""
    if raw is None:
        return True
    s = raw.strip().lower()
    if s in _ANON_TOKENS:
        return True
    return not any(c.isdigit() for c in s)


def normalize_number_key(raw):
    """Light cache-key normalization: keep a leading '+', drop all non-digits.

    Authoritative E.164 normalization happens server-side; this only collapses
    formatting differences so '+61 3...' and '03...' that are equal as typed hit
    one cache entry.
    """
    s = raw.strip()
    plus = s.startswith('+')
    digits = ''.join(c for c in s if c.isdigit())
    return ('+' if plus else '') + digits


def validate_term(term, min_len, max_len):
    """Return the trimmed term if within [min_len, max_len], else None."""
    if term is None:
        return None
    s = term.strip()
    if len(s) < min_len or len(s) > max_len:
        return None
    return s


def normalize_term_key(term):
    """Cache-key normalization for search terms: lowercased, whitespace-collapsed."""
    return ' '.join(term.strip().lower().split())
