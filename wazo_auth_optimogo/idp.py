import logging

try:                                   # on the PBX these exist; real imports run ON-box only
    from wazo_auth.plugins.idp.base import BaseIDP  # pragma: no cover
    from wazo_auth.exceptions import InvalidUsernamePassword as _InvalidUsernamePassword  # pragma: no cover
except ImportError:                    # off-box / unit-test path — stubs used here
    class BaseIDP:                     # minimal stand-in
        def load(self, dependencies): ...

    class _InvalidUsernamePassword(Exception):
        def __init__(self, login=None):
            super().__init__(login)

from wazo_dird_optimogo.breaker import CircuitBreaker
from .config import load_config
from .exceptions import IntrospectError
from .http_client import OptimoGoIntrospectClient

logger = logging.getLogger(__name__)

_BREAKER_FAILURE_THRESHOLD = 5
_BREAKER_COOLDOWN_SECONDS = 30


class InvalidBridgeToken(_InvalidUsernamePassword):
    """Raised when the OptimoGo bridge token cannot be verified into a Wazo user."""


class OptimoGoIDP(BaseIDP):
    # 'optimogo' is a dedicated SSO-only method (S1). Wazo users enabled for
    # OptimoGo SSO must be set to authentication_method='optimogo' via wazo-auth's
    # IDP user-association API; they lose Wazo password login (like SAML/LDAP).
    authentication_method = 'optimogo'

    def load(self, dependencies):
        super().load(dependencies)
        # Config lives at config['idp_plugins']['optimogo'] (S2 — ldap/saml convention).
        cfg = load_config(dependencies['config']['idp_plugins']['optimogo'])
        self._wazo_tenant_uuid = cfg['wazo_tenant_uuid']
        self._client = OptimoGoIntrospectClient(
            base_url=cfg['introspect_base_url'],
            api_key=cfg['auth_bridge_key'],
            connect_timeout=cfg['connect_timeout'],
            read_timeout=cfg['read_timeout'],
            verify=cfg['verify_certificate'],
        )
        self._breaker = CircuitBreaker(
            failure_threshold=_BREAKER_FAILURE_THRESHOLD,
            cooldown=_BREAKER_COOLDOWN_SECONDS,
        )
        self._backend = dependencies['backends']['wazo_user'].obj   # S2: confirmed injection key
        self._user_service = dependencies['user_service']           # S2: confirmed injection key

    def can_authenticate(self, args: dict) -> bool:
        return (
            args.get('backend') == 'optimogo'
            and bool(args.get('login'))
            and bool(args.get('password'))
        )

    def verify_auth(self, args: dict):
        """Verify an OptimoGo bridge token and return (backend, authoritative_email).

        Raises:
            InvalidBridgeToken: if the breaker is open, the token is inactive,
                the tenant UUID mismatches, the user cannot be resolved, or
                the introspection call fails.
        """
        if not self._breaker.allow():
            raise InvalidBridgeToken(args.get('login'))

        try:
            result = self._client.introspect(args['password'])
            self._breaker.record_success()
        except IntrospectError as e:
            self._breaker.record_failure()
            logger.info('optimogo introspect failed: %s', e)
            raise InvalidBridgeToken(args.get('login')) from e

        if not result.get('active'):
            raise InvalidBridgeToken(args.get('login'))

        if result.get('wazo_tenant_uuid') != self._wazo_tenant_uuid:
            raise InvalidBridgeToken(args.get('login'))

        # Use the authoritative email from the introspection result — ignore client login.
        email = result.get('email')
        login = self._resolve_enabled_user(email, self._wazo_tenant_uuid)
        if login is None:
            raise InvalidBridgeToken(email)

        return self._backend, login

    def _resolve_enabled_user(self, email, tenant_uuid):
        """Return the login (email) iff exactly one ENABLED user with this CONFIRMED
        email exists globally AND it is in the asserted tenant; else None.

        Global-uniqueness guard closes the cross-tenant duplicate-email hole, because
        wazo_user.get_metadata later resolves the login via the global get_user_by_login.

        list_users return shape: dict with 'items' key (wazo-auth 26.x) or bare list
        — both are handled by the isinstance check below.
        """
        try:
            result = self._user_service.list_users(login=email)
            users = result['items'] if isinstance(result, dict) else result
        except Exception as e:
            logger.warning('optimogo: user resolution failed for %s: %s', email, e)
            return None

        matches = [
            u for u in users
            if u.get('enabled') is True
            and any(
                e.get('confirmed') and e.get('address', '').lower() == email.lower()
                for e in u.get('emails', [])
            )
        ]

        if len(matches) != 1:           # 0 = no match; >1 = cross-tenant ambiguity → refuse
            return None
        if matches[0].get('tenant_uuid') != tenant_uuid:
            return None

        return email
