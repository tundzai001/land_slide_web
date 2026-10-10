"""The station map query rejects invalid geographic bounds before DB work."""

import unittest

from fastapi import HTTPException

from app.features.stations.query_router import parse_station_bbox


class StationBBoxTests(unittest.TestCase):
    def test_finite_geographic_bounds(self):
        self.assertEqual(parse_station_bbox(" 103,20,108,24 "), (103.0, 20.0, 108.0, 24.0))
        for value in ("NaN,20,108,24", "103,-inf,108,24", "103,20,181,24",
                      "103,20,108,91", "108,20,103,24", "103,24,108,20", "103,20,108"):
            with self.subTest(value=value), self.assertRaises(HTTPException) as error:
                parse_station_bbox(value)
            self.assertEqual(error.exception.status_code, 422)
