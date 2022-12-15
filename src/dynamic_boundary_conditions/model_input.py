# -*- coding: utf-8 -*-
"""
@Script name: model_input.py
@Description:
@Author: sli229
@Date: 8/12/2022
"""

import logging
import pathlib
import geopandas as gpd
import pandas as pd
from typing import Literal
import xarray
from shapely.geometry import Polygon
from geocube.api.core import make_geocube
from src.digitaltwin import setup_environment
from src.dynamic_boundary_conditions import main_rainfall, thiessen_polygons, hirds_rainfall_data_from_db, hyetograph

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

formatter = logging.Formatter("%(levelname)s:%(asctime)s:%(name)s:%(message)s")
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

log.addHandler(stream_handler)


def sites_voronoi_intersect_catchment(
        sites_in_catchment: gpd.GeoDataFrame,
        catchment_polygon: Polygon) -> gpd.GeoDataFrame:
    """
    Get the intersection of rainfall sites coverage areas (thiessen polygons) and the catchment area,
    i.e. return the overlapped areas (intersections).

    Parameters
    ----------
    sites_in_catchment : gpd.GeoDataFrame
        Rainfall sites coverage areas (thiessen polygons) that intersects or are within the catchment area.
    catchment_polygon : Polygon
        Desired catchment area.
    """
    catchment_area = gpd.GeoDataFrame(index=[0], crs='epsg:4326', geometry=[catchment_polygon])
    intersections = gpd.overlay(sites_in_catchment, catchment_area, how="intersection")
    return intersections


def sites_coverage_in_catchment(
        sites_in_catchment: gpd.GeoDataFrame,
        catchment_polygon: Polygon) -> gpd.GeoDataFrame:
    """
    Get the intersection of rainfall sites coverage areas (thiessen polygons) and the catchment area, and
    calculate the area and the percentage of area covered by each rainfall site inside the catchment area.

    Parameters
    ----------
    sites_in_catchment : gpd.GeoDataFrame
        Rainfall sites coverage areas (thiessen polygons) that intersects or are within the catchment area.
    catchment_polygon : Polygon
        Desired catchment area.
    """
    sites_coverage = sites_voronoi_intersect_catchment(sites_in_catchment, catchment_polygon)
    sites_coverage['area_in_km2'] = sites_coverage.to_crs(3857).area / 1e6
    sites_area_total = sites_coverage['area_in_km2'].sum()
    sites_area_percent = sites_coverage['area_in_km2'] / sites_area_total
    sites_coverage.insert(3, "area_percent", sites_area_percent)
    return sites_coverage


def mean_catchment_rainfall(hyetograph_data: pd.DataFrame, sites_coverage: gpd.GeoDataFrame) -> pd.DataFrame:
    """
    Calculate the mean catchment rainfall depths and intensities (weighted average of gauge measurements)
    across all durations using the thiessen polygon method.

    Parameters
    ----------
    hyetograph_data : pd.DataFrame
        Hyetograph data for sites within the catchment area.
    sites_coverage : gpd.GeoDataFrame
        Contains the area and the percentage of area covered by each rainfall site inside the catchment area.
    """
    increment_mins = hyetograph_data["mins"][1] - hyetograph_data["mins"][0]
    mean_catchment_rain = hyetograph_data.copy()
    sites_column_list = list(mean_catchment_rain.columns.values[:-3])
    for site_id in sites_column_list:
        site_area_percent = sites_coverage.query("site_id == @site_id")["area_percent"].values[0]
        mean_catchment_rain[f"{site_id}"] = mean_catchment_rain[f"{site_id}"] * site_area_percent
    mean_catchment_rain["rain_depth_mm"] = mean_catchment_rain[sites_column_list].sum(axis=1)
    mean_catchment_rain["rain_intensity_mmhr"] = mean_catchment_rain["rain_depth_mm"] / increment_mins * 60
    mean_catchment_rain = mean_catchment_rain[["mins", "hours", "seconds", "rain_depth_mm", "rain_intensity_mmhr"]]
    return mean_catchment_rain


def spatial_uniform_model_input(
        hyetograph_data: pd.DataFrame,
        sites_coverage: gpd.GeoDataFrame,
        bg_flood_path: pathlib.Path):
    """
    Write the relevant mean catchment rainfall data (i.e. 'seconds' and 'rain_intensity_mmhr' columns) in a text file
    (rain_forcing.txt). This can be used as spatially uniform rainfall input into the BG-Flood model.

    Parameters
    ----------
    hyetograph_data : pd.DataFrame
        Hyetograph data for sites within the catchment area.
    sites_coverage : gpd.GeoDataFrame
        Contains the area and the percentage of area covered by each rainfall site inside the catchment area.
    bg_flood_path : pathlib.Path
        BG-Flood file path.
    """
    mean_catchment_rain = mean_catchment_rainfall(hyetograph_data, sites_coverage)
    spatial_uniform_input = mean_catchment_rain[["seconds", "rain_intensity_mmhr"]]
    spatial_uniform_input.to_csv(bg_flood_path/"rain_forcing.txt", header=None, index=None, sep="\t")


def create_rain_data_cube(hyetograph_data: pd.DataFrame, sites_coverage: gpd.GeoDataFrame):
    """
    Create the rainfall depths and intensities data cube for the catchment area across all durations.

    Parameters
    ----------
    hyetograph_data : pd.DataFrame
        Hyetograph data for sites within the catchment area.
    sites_coverage : gpd.GeoDataFrame
        Contains the area and the percentage of area covered by each rainfall site inside the catchment area.
    """
    increment_mins = hyetograph_data["mins"][1] - hyetograph_data["mins"][0]
    hyetograph_data_long = pd.DataFrame()
    for index, row in hyetograph_data.iterrows():
        hyeto_time_slice = row[:-3].to_frame("rain_depth_mm").rename_axis("site_id").reset_index()
        hyeto_time_slice["rain_intensity_mmhr"] = hyeto_time_slice["rain_depth_mm"] / increment_mins * 60
        hyeto_time_slice = hyeto_time_slice.assign(mins=row["mins"], hours=row["hours"], seconds=row["seconds"])
        hyetograph_data_long = pd.concat([hyetograph_data_long, hyeto_time_slice])

    sites_coverage = sites_coverage.drop(columns=["site_name", "area_in_km2", "area_percent"])
    hyeto_data_w_geom = hyetograph_data_long.merge(sites_coverage, how="inner")
    hyeto_data_w_geom = gpd.GeoDataFrame(hyeto_data_w_geom)

    rain_data_cube = make_geocube(
        vector_data=hyeto_data_w_geom,
        measurements=["rain_depth_mm", "rain_intensity_mmhr"],
        resolution=(-0.0001, 0.0001),
        group_by="seconds",
        fill=0)

    return rain_data_cube


def spatial_varying_model_input(rain_data_cube: xarray.Dataset, bg_flood_path: pathlib.Path):
    """
    Write the rainfall intensities data cube out in NetCDF format (rain_forcing.nc).
    This can be used as spatially varying rainfall input into the BG-Flood model.

    Parameters
    ----------
    rain_data_cube : xarray.Dataset
        Rainfall depths and intensities data cube for the catchment area across all durations.
    bg_flood_path : pathlib.Path
        BG-Flood file path.
    """
    spatial_varying_input = rain_data_cube.drop_vars("rain_depth_mm")
    spatial_varying_input.to_netcdf(bg_flood_path/"rain_forcing.nc")


def main():
    # BG-Flood path
    bg_flood_path = pathlib.Path(r"U:/Research/FloodRiskResearch/DigitalTwin/BG-Flood/BG-Flood_Win10_v0.6-a")
    # Catchment polygon
    catchment_file = pathlib.Path(r"src\dynamic_boundary_conditions\catchment_polygon.shp")
    catchment_polygon = main_rainfall.catchment_area_geometry_info(catchment_file)
    # Connect to the database
    engine = setup_environment.get_database()
    # Get all rainfall sites (thiessen polygons) coverage areas that are within the catchment area
    sites_in_catchment = thiessen_polygons.thiessen_polygons_from_db(engine, catchment_polygon)

    # Requested scenario
    rcp = None  # 2.6
    time_period = None  # "2031-2050"
    ari = 50  # 100
    # For a requested scenario, get all rainfall data for sites within the catchment area from the database
    # Set idf to False for rain depth data and to True for rain intensity data
    rain_depth_in_catchment = hirds_rainfall_data_from_db.rainfall_data_from_db(
        engine, sites_in_catchment, rcp, time_period, ari, idf=False)
    # Get hyetograph data for all sites within the catchment area
    hyetograph_data = hyetograph.get_hyetograph_data(
        rain_depth_in_catchment,
        storm_length_hrs=48,
        time_to_peak_hrs=24,
        increment_mins=10,
        interp_method="cubic",
        hyeto_method="alt_block")
    # Create interactive hyetograph plots for sites within the catchment area
    hyetograph.hyetograph(hyetograph_data, ari)

    # Write out mean catchment rainfall data in a text file (used as spatially uniform rainfall input into BG-Flood)
    sites_coverage = sites_coverage_in_catchment(sites_in_catchment, catchment_polygon)
    spatial_uniform_model_input(hyetograph_data, sites_coverage, bg_flood_path)

    # Write out data cube in netcdf format (used as spatially varying rainfall input into BG-Flood)
    rain_data_cube = create_rain_data_cube(hyetograph_data, sites_coverage)
    spatial_varying_model_input(rain_data_cube, bg_flood_path)


if __name__ == "__main__":
    main()
