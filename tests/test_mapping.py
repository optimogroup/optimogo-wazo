from wazo_dird_optimogo.mapping import map_match, map_search_row, map_results

PREFIX = 'Maybe: '


def test_matched_maps_all_columns():
    match = {'name': 'Acme Plumbing', 'number': '+61399999999', 'customer_id': 123,
             'contact_name': 'John Smith', 'match_state': 'matched'}
    out = map_match(match, PREFIX)
    assert out == {
        'id': 'customer:123:number:+61399999999',
        'name': 'Acme Plumbing',
        'number': '+61399999999',
        'customer_id': 123,
        'contact_name': 'John Smith',
        'display_name': 'Acme Plumbing',
    }


def test_ambiguous_applies_prefix_once_from_raw_name():
    match = {'name': 'Acme Plumbing', 'display_name': 'Acme Plumbing',
             'number': '+61399999999', 'customer_id': 123,
             'match_state': 'ambiguous', 'candidate_count': 3}
    out = map_match(match, PREFIX)
    assert out['display_name'] == 'Maybe: Acme Plumbing'   # prefixed exactly once
    assert out['name'] == 'Acme Plumbing'


def test_none_match_returns_none():
    assert map_match(None, PREFIX) is None


def test_empty_strings_become_none():
    match = {'name': 'Acme', 'number': '+61', 'customer_id': 9,
             'contact_name': '  ', 'match_state': 'matched'}
    out = map_match(match, PREFIX)
    assert out['contact_name'] is None


def test_search_rows_mapped_with_per_number_id():
    rows = [
        {'name': 'Acme', 'number': '+61399999999', 'customer_id': 123, 'contact_name': None},
        {'name': 'John', 'number': '+61400000000', 'customer_id': 123,
         'contact_name': 'John', 'display_name': 'Acme — John'},
    ]
    out = map_results(rows)
    assert [r['id'] for r in out] == [
        'customer:123:number:+61399999999',
        'customer:123:number:+61400000000',
    ]
    assert out[1]['display_name'] == 'Acme — John'


def test_server_id_preserved_when_present():
    row = {'id': 'custom-id', 'name': 'Acme', 'number': '+61', 'customer_id': 1}
    assert map_search_row(row)['id'] == 'custom-id'
