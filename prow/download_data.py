"""
Module for functionality to download various datasets and save to local folder.
"""
import os, requests
from pathlib import Path
from tqdm import tqdm

import pandas as pd

import osmnx as ox
import networkx as nx
import geopandas as gpd

from .utils.utils import *
from .utils import gpx_converter
from .utils.interpolate import batch_geo_interpolate_df

def download_public_gps_data(region: str, fn="") -> None:
    """Download dataset of public GPS traces from an OSM planet dump. Convert to csv.
    Do not perform interpolation here, save that for each smaller subregion.
    TODO: delete unzipped folder after csv conversion to save space
    
    Args:
        region (str): Region name from [here](http://zverik.openstreetmap.ru/gps/files/extracts/europe/great_britain)
        fn (str, optional): Prefix for output data. Defaults to "".
    """
    csv_fn = fn+".csv"
    if os.path.isfile(csv_fn):
        print(f"Public GPS data found at {csv_fn}")
        return
    
    print(f"Downloading to {csv_fn}...")
    os.system("echo Starting download...")
    os.system(f"curl -o {fn}.tar.xz http://zverik.openstreetmap.ru/gps/files/extracts/europe/great_britain/{region}.tar.xz")
    os.system("echo Unzipping...")
    os.system(f"tar -xvf {fn}.tar.xz -C {os.path.dirname(fn)}") #TODO: unzip to given folder name so that we can list paths of correct folder
    os.system("echo Deleting archive")
    os.system(f"rm {fn}.tar.xz")
    
    print("Converting...")
    all_gps_paths = list(Path("data/public/gpx-planet-2013-04-09").rglob("*.gpx")) #TODO: see above TODO
    
    frames = []
    for idx,gps_path in tqdm(enumerate(all_gps_paths)):
        df = gpx_converter.Converter(input_file=gps_path).gpx_to_dataframe(i=idx)
        df = df[["latitude", "longitude", "trackid"]]
        df = df.loc[(df[["latitude", "longitude"]] != 0).all(axis=1), :]
        frames.append(df)
        
    all_gps_raw_df = pd.concat(frames, ignore_index=True)
    all_gps_raw_df.to_csv(csv_fn, index=False)

    print("Done")

def download_row_data(authority_code: str, fn="") -> None:
    """Download RoW dataset to local folder. Convert to CSV. Interpolate spatially along the edges.

    Args:
        authority_code (str): two letter authority code for authorities supported [here](https://www.rowmaps.com/datasets) 
        fn (str, optional): Prefix for output data. Defaults to "".
    """
    csv_fn = fn+".csv"
    if os.path.isfile(csv_fn):
        print(f"RoW data found at {csv_fn}")
        return
    
    print(f"Downloading to {csv_fn}...")
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.12; rv:55.0) Gecko/20100101 Firefox/55.0',}
    #final_interpolated_row_dfs = []
    
    print("Downloading RoW data for ", authority_code)
    row_response = requests.get("https://www.rowmaps.com/getgpx.php", params={"l": authority_code, "w": "no"}, headers=headers)

    with open(fn+".gpx", "wb") as f:
        f.write(row_response.content)
        #TODO: skip this step and pass content directly to converter

    print("Converting...")
    row_raw_df = gpx_converter.Converter(input_file=fn+".gpx").gpx_to_dataframe()

    #row_raw_df["trackid"] += i * 1000000

    print("Interpolating...")
    row_df = batch_geo_interpolate_df(row_raw_df, dist_m=INTERPOLATION_DIST_ROW_GPS, segmentation=False)

    #final_interpolated_row_dfs += [row_df]

    print("Done")
    
    #pd.concat(final_interpolated_row_dfs, ignore_index=True).to_csv(csv_fn)
    row_df.to_csv(csv_fn)
    

def get_graph_boundary(authority: str) -> list:
    """Get boundary of given authority name and split up into small square chunks.
    Chunk size set by constant SPLIT_POLYGON_BOX_LENGTH. Setting smaller means 
    map-matching will be quicker as there are less point to search per region.

    Args:
        authority (str): authority full name or list of authorities 
        from list [here](https://www.rowmaps.com/datasets)

    Returns:
        list: list of shapely.geometry.MultiPolygon geometries representing
        smaller regions to analyse in authority
    """
    
    authority = [authority]
    gdf = ox.geocode_to_gdf(authority, buffer_dist=10)#500
    
    if len(authority) > 1:
        geom = gdf["geometry"].unary_union
    else:
        geom = gdf["geometry"][0]
    
    split_geom = ox.utils_geo._quadrat_cut_geometry(geom, quadrat_width=metres_to_dist(SPLIT_POLYGON_BOX_LENGTH))
    split_geom_gdf = gpd.GeoDataFrame({"geometry": split_geom}, crs=gdf.crs)
    
    polygons = split_geom_gdf["geometry"].to_list()
    return polygons

def download_graphs(graph_boundary: list, fn="") -> None:
    """Download all graphs from OSM for each region geometry in list of boundaries.
    Each graph contains the OSM way network with all OSM attributes within boundary.
    OSM highways included are footways, cycleways, bridleways, paths and tracks.

    Args:
        graph_boundary (list): List of shapely.geometry.MultiPolygon geometries
        representing boundaries for graphs to download
        fn (str, optional): File prefix for graphs to download. Defaults to "".
    """
    print("Downloading...")

    for i,geom in tqdm(enumerate(graph_boundary)):
        if os.path.isfile(f"{fn}_{i}.graphml"):
            print(f"Graph found for {i}th geometry, continuing")
            continue

        try:
            G = ox.graph_from_polygon(geom,
                           custom_filter='["highway"~"footway|cycleway|bridleway|path|track"]', 
                           retain_all=True, simplify=False).to_undirected()
        except ValueError:
            G = nx.MultiGraph() #empty
        
        ox.save_graphml(G, f"{fn}_{i}.graphml")

    print("Done")