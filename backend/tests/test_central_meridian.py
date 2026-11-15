from processors.geodetic import parse_vn2000_central_meridian


def test_central_meridian_formats_and_long_whitespace():
    assert parse_vn2000_central_meridian('105°30\'') == (105.5, 'deg_min')
    assert parse_vn2000_central_meridian('105   30') == (105.5, 'deg_min')
    assert parse_vn2000_central_meridian('104.45') == (104.75, 'deg_min_compact')
    assert parse_vn2000_central_meridian('105' + ' ' * 10000 + 'x') == (105.0, 'default')
