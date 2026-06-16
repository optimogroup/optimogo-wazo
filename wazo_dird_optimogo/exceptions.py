class OptimoGoError(Exception):
    """Base class for all OptimoGo plugin errors."""


class OptimoGoAuthError(OptimoGoError):
    """401/403 from OptimoGo: bad or rotated API key. Never trips the breaker."""


class OptimoGoTimeout(OptimoGoError):
    """Connect or read timeout talking to OptimoGo. Feeds the breaker."""


class OptimoGoUnavailable(OptimoGoError):
    """5xx, 429, or connection/DNS/TLS failure from OptimoGo. Feeds the breaker."""


class OptimoGoLookupError(OptimoGoError):
    """200 with malformed/oversized/wrong-type body, or other 4xx. Feeds the breaker."""
