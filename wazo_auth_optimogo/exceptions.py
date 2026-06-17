class IntrospectError(Exception):
    """Base class for all OptimoGo introspection errors."""


class IntrospectAuthError(IntrospectError):
    """401/403 from OptimoGo introspect endpoint: bad or rotated API key."""


class IntrospectTimeout(IntrospectError):
    """Connect or read timeout talking to OptimoGo introspect endpoint."""


class IntrospectUnavailable(IntrospectError):
    """5xx, 429, or connection/DNS/TLS failure from OptimoGo introspect endpoint."""
