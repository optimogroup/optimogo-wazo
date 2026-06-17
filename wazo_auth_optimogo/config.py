_REQUIRED = ('optimogo_base_url', 'tenant_schema', 'wazo_tenant_uuid', 'auth_bridge_key')


def load_config(raw: dict) -> dict:
    """Validate and normalise the optimogo IDP plugin config.

    Only the keys this plugin needs are read; extra keys (e.g. ``enabled``,
    ``priority``) are silently ignored so callers can pass the full
    ``config['idp_plugins']['optimogo']`` dict directly.

    Raises:
        ValueError: if a required key is absent/empty, or if
            ``optimogo_base_url`` is not https.
    """
    for key in _REQUIRED:
        if not raw.get(key):
            raise ValueError(f'optimogo idp config missing required key: {key}')

    base = str(raw['optimogo_base_url']).rstrip('/')
    if not base.startswith('https://'):
        raise ValueError('optimogo_base_url must be https://')

    schema = raw['tenant_schema']
    return {
        'introspect_base_url': f'{base}/api/wazo/auth/{schema}',
        'tenant_schema': schema,
        'wazo_tenant_uuid': raw['wazo_tenant_uuid'],
        'auth_bridge_key': raw['auth_bridge_key'],
        'verify_certificate': raw.get('verify_certificate', True),
        'connect_timeout': raw.get('connect_timeout', 2),
        'read_timeout': raw.get('read_timeout', 4),
    }
