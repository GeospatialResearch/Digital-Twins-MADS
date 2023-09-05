# -*- coding: utf-8 -*-
"""
This script runs each module in the Digital Twin using a Sample Polygon.
"""

from types import ModuleType
from typing import Dict

import geopandas as gpd
from newzealidar import datasets, process
from src.dynamic_boundary_conditions.rainfall import main_rainfall
from src.dynamic_boundary_conditions.river import main_river
from src.dynamic_boundary_conditions.tide import main_tide_slr

from src.digitaltwin import run
from src.digitaltwin.utils import LogLevel
from src.flood_model import bg_flood_model


def main(selected_polygon_gdf: gpd.GeoDataFrame, modules_with_log_levels: Dict[ModuleType, LogLevel]) -> None:
    for module, log_level in modules_with_log_levels.items():
        module.main(selected_polygon_gdf, log_level=log_level)


def run_with_default_log_level(selected_polygon_gdf: gpd.GeoDataFrame) -> None:
    main(selected_polygon_gdf, DEFAULT_MODULE_TO_LOG_LEVEL)


DEFAULT_MODULE_TO_LOG_LEVEL = {
    run: LogLevel.DEBUG,
    datasets: LogLevel.DEBUG,  # only need to run it one time to initiate db.dataset table
    process: LogLevel.DEBUG,
    main_rainfall: LogLevel.DEBUG,
    main_tide_slr: LogLevel.DEBUG,
    main_river: LogLevel.DEBUG,
    bg_flood_model: LogLevel.DEBUG,
}

if __name__ == '__main__':
    # Define a dictionary mapping each module to its log level
    sample_polygon = gpd.GeoDataFrame.from_file("selected_polygon.geojson")
    main(sample_polygon, DEFAULT_MODULE_TO_LOG_LEVEL)
