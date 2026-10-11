"""Validation for UTM 48N project DEM grids and station placement."""

import unittest

from fastapi import HTTPException

from app.features.stations.common import calculate_station_location
from app.shared.project_dem import inspect_ascii_grid


class ProjectDemTests(unittest.TestCase):
    def setUp(self):
        self.valid_grid = (
            "ncols 2\n"
            "nrows 2\n"
            "xllcorner 454959.202\n"
            "yllcorner 2326094.284\n"
            "cellsize 1\n"
            "NODATA_value -9999\n"
            "100.0 101.5\n"
            "98 99\n"
        ).encode()

    def test_inspects_grid_and_uses_the_selected_cell_origin(self):
        metadata = inspect_ascii_grid(self.valid_grid)
        self.assertEqual(metadata["crs"], "EPSG:32648")
        self.assertEqual((metadata["ncols"], metadata["nrows"]), (2, 2))
        self.assertEqual(metadata["elevation_min"], 98)
        self.assertEqual(metadata["elevation_max"], 101.5)

    def test_rejects_invalid_grid_dimensions_and_cell_counts(self):
        for content in (
            self.valid_grid.replace(b"ncols 2", b"ncols 0"),
            self.valid_grid.replace(b"100.0 101.5\n98 99", b"100.0 101.5\n98"),
            self.valid_grid.replace(b"454959.202", b"-1"),
            self.valid_grid.replace(b"100.0 101.5", b"NaN 101.5"),
        ):
            with self.subTest(content=content[-16:]), self.assertRaises(HTTPException):
                inspect_ascii_grid(content)

    def test_dem_grid_station_point_takes_priority_over_sensor_origins(self):
        selected = {"lat": 22.6, "lon": 103.8, "h": 101.5, "source": "project-dem-grid"}
        sensors = {"gnss": {"lat": 22.7, "lon": 103.9, "h": 90}}
        self.assertEqual(calculate_station_location(sensors, selected), selected)


if __name__ == "__main__":
    unittest.main()
