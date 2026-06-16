def _none_if_empty(value):
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _canonical_id(customer_id, number):
    return f'customer:{customer_id}:number:{number}'


def _row_id(row, number):
    return _none_if_empty(row.get('id')) or _canonical_id(row.get('customer_id'), number)


def map_match(match, ambiguous_prefix):
    """Map a reverse 'match' object to a dird field dict, or None.

    The plugin owns the ambiguous prefix: when match_state == 'ambiguous' the
    display label is `ambiguous_prefix + name` (built from the raw name so the
    prefix is applied exactly once regardless of the server's display_name).
    """
    if not match:
        return None
    name = _none_if_empty(match.get('name'))
    number = _none_if_empty(match.get('number'))
    if match.get('match_state') == 'ambiguous' and name:
        display = f'{ambiguous_prefix}{name}'
    else:
        display = _none_if_empty(match.get('display_name')) or name
    return {
        'id': _row_id(match, number),
        'name': name,
        'number': number,
        'customer_id': match.get('customer_id'),
        'contact_name': _none_if_empty(match.get('contact_name')),
        'display_name': display,
    }


def map_search_row(row):
    name = _none_if_empty(row.get('name'))
    number = _none_if_empty(row.get('number'))
    return {
        'id': _row_id(row, number),
        'name': name,
        'number': number,
        'customer_id': row.get('customer_id'),
        'contact_name': _none_if_empty(row.get('contact_name')),
        'display_name': _none_if_empty(row.get('display_name')) or name,
    }


def map_results(rows):
    return [map_search_row(r) for r in rows]
