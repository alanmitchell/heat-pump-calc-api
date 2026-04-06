"""This module provides static information from the AkWarm Energy Library
and from TMY3 files.
When this module is imported, it reads data from files in the
'data' directory located in this folder and reads some remotely stored
data files via HTTP requests.  The data is stored as module-level
variables and made available to other modules via functions.
See the bottom is file for documentation of those datasets.
"""

import os
import io
import functools
import urllib
import time
from typing import List
import threading

import numpy as np
import pandas as pd
import requests

from general.models import Choice
from general.utils import nan_to_none, dataframe_to_models
from library.models import City, Utility, Fuel, FuelPrice, TMYmeta, TMYdataset

# Most of the data files are located remotely and are retrieved via
# an HTTP request.
# The base URL to the site where the remote files are located
base_url = "https://github.com/alanmitchell/akwlib-export/raw/main/data/v01/"

# This constant controls how frequently the library goes back to the GitHub server to
# download the freshest AkWarm data.
LIB_TIMEOUT = 12.0  # units are Hours

# URL for fetching utility rate overrides from a Google Sheets spreadsheet
GSHEET_OVERRIDES_URL = "https://docs.google.com/spreadsheets/d/1vWYfVsTmfAZ5yrLD0ljmDY7w8-P9VdlNxycXm5MY5DI/gviz/tq?tqx=out:csv"


def get_df(file_path):
    """Returns a Pandas DataFrame that is found at the 'file_path'
    below the Base URL for accessing data.  The 'file_path' should end
    with '.pkl' and points to a pickled, compressed (bz2), Pandas DataFrame.
    """
    b = requests.get(urllib.parse.urljoin(base_url, file_path)).content
    df = pd.read_pickle(io.BytesIO(b), compression="bz2")
    return df


def _fetch_gsheet_overrides():
    """Fetch utility rate overrides from Google Sheets. Returns a DataFrame indexed by ID."""
    resp = requests.get(GSHEET_OVERRIDES_URL, timeout=15)
    resp.raise_for_status()

    df = pd.read_csv(io.StringIO(resp.text))

    # Clean dollar signs and commas from all numeric columns
    value_cols = (
        ['PCE', 'CustomerChg', 'DemandCharge']
        + [f'kWh{i}' for i in range(1, 6)]
        + [f'Rate{i}' for i in range(1, 6)]
    )
    for col in value_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace('$', '', regex=False).str.replace(',', '', regex=False)
            df[col] = pd.to_numeric(df[col], errors='coerce')

    df['ID'] = pd.to_numeric(df['ID'], errors='coerce')
    df = df.dropna(subset=['ID'])
    df['ID'] = df['ID'].astype(int)
    df.set_index('ID', inplace=True)

    return df


def _apply_overrides(df_util, df_overrides):
    """Apply spreadsheet overrides to df_util in place."""
    for util_id, row in df_overrides.iterrows():
        if util_id not in df_util.index:
            print(f"Override ID {util_id} not found in df_util, skipping.")
            continue

        # Override scalar columns
        for col in ['PCE', 'CustomerChg', 'DemandCharge']:
            df_util.at[util_id, col] = row[col]

        # Build Blocks list of tuples; blank values remain as NaN
        blocks = []
        for i in range(1, 6):
            kwh = row.get(f'kWh{i}', np.nan)
            rate = row.get(f'Rate{i}', np.nan)
            blocks.append((kwh, rate))
        df_util.at[util_id, 'Blocks'] = blocks


# -----------------------------------------------------------------
# Functions to provide the library data to the rest of the
# application.
def cities() -> List[Choice]:
    """List of all (city name, city ID), alphabetically sorted."""
    city_list = list(zip(df_city.Name, df_city.index))
    city_list.sort()  # sorts in place; returns None
    return [Choice(label=label, id=id) for label, id in city_list]

@functools.lru_cache(maxsize=50)
def city_from_id(city_id) -> City:
    """Returns a dictionary containing the city information for the City
    identified by 'city_id'.
    """
    city_dict = df_city.loc[city_id].to_dict()
    # turn utility list into list of Choice items
    city_dict["ElecUtilities"] = [
        {"label": label, "id": id} for label, id in city_dict["ElecUtilities"]
    ]
    # do the following to replace NaN's with None
    city_dict = nan_to_none(city_dict)
    city_dict["id"] = city_id
    return City(**city_dict)


# --------------------------------------------------------------------------------------


def utilities() -> List[Choice]:
    """List of all utility rate structures, sorted by utility rate name."""
    util_list = list(zip(df_util.Name, df_util.index))
    util_list.sort()
    return [Choice(label=label, id=id) for label, id in util_list]

@functools.lru_cache(maxsize=50)
def util_from_id(util_id) -> Utility:
    """Returns a dictionary containing all of the Utility information for
    the Utility identified by util_id.
    """
    return_dict = nan_to_none(df_util.loc[util_id].to_dict())
    return_dict["id"] = util_id
    return Utility(**return_dict)


# --------------------------------------------------------------------------------------


def fuels() -> List[Choice]:
    """Returns a list of fuel names and IDs."""
    fuel_list = list(zip(df_fuel.desc, df_fuel.index))
    return [Choice(label=label, id=id) for label, id in fuel_list]

@functools.lru_cache(maxsize=50)
def fuel_from_id(fuel_id) -> Fuel:
    """Returns fuel information for the fuel with
    and ID of 'fuel_id'
    """
    fuel_dict = nan_to_none(df_fuel.loc[fuel_id].to_dict())
    fuel_dict["id"] = fuel_id
    return Fuel(**fuel_dict)

@functools.lru_cache(maxsize=50)
def fuel_price(fuel_id, city_id) -> FuelPrice:
    """Returns the fuel price for the fuel identified by the ID of
    'fuel_id' for the city identified by 'city_id'.
    """
    city = df_city.loc[city_id]
    city_name = city.Name
    fuel = df_fuel.loc[fuel_id]
    fuel_name = fuel.desc
    if type(fuel.price_col) == str:
        price = city[fuel.price_col]
    else:
        # Price column is a NaN and not present for electricity
        price = None

    return_dict = nan_to_none({"city": city_name, "fuel": fuel_name, "price": price})
    return FuelPrice(**return_dict)


# --------------------------------------------------------------------------------------


def tmys() -> List[TMYmeta]:
    """Returns a list of available TMY sites and associated info."""
    return dataframe_to_models(df_tmy_meta, TMYmeta)


@functools.lru_cache(maxsize=50)  # caches the TMY data cuz retrieved remotely
def tmy_from_id(tmy_id: int, site_info_only: bool = False) -> TMYdataset:
    """Returns a list of TMY hourly records and meta data for the climate site identified
    by 'tmy_id'.
    """
    site_info = TMYmeta(**df_tmy_meta.loc[tmy_id].to_dict())
    if not site_info_only:
        df_records = get_df(f"tmy3/{tmy_id}.pkl")
        df_records["hour"] = list(range(0, 24)) * 365
        recs_dict = df_records.to_dict(orient="list")
        return TMYdataset(site_info=site_info, hourly_data=recs_dict)
    else:
        return TMYdataset(site_info=site_info)

@functools.lru_cache(maxsize=50)  # caches the TMY data cuz retrieved remotely
def tmy_df_from_id(tmy_id: int) -> pd.DataFrame:
    """Returns a DataFrame with columns limited to what is typically needed
    """
    df = get_df(f"tmy3/{tmy_id}.pkl")[["db_temp", "month"]]
    df["day_of_year"] = [i for i in range(1, 366) for _ in range(24)]
    return df

# --------------------------------------------------------------------------------------


def refresh_data():
    """Key datasets are read in here and placed in module-level variables,
    listed below this function.
    """
    global df_tmy_meta
    global df_city
    global df_util
    global df_fuel
    global last_lib_download_ts  # tracks time of last refresh

    print("acquiring library data...")

    # Key datasets are read in here and are available as module-level
    # variables for use in the functions above.

    # read in the DataFrame that describes the available TMY3 climate files.
    df_tmy_meta = get_df("tmy3/tmy3_meta.pkl")
    df_tmy_meta["tmy_id"] = df_tmy_meta.index.values

    # Read in the other City and Utility Excel files.
    df_city = get_df("city.pkl")
    # Need to add an empty column for the price of Wood Pellets
    df_city["WoodPelletsPrice"] = float("nan")

    # Retrive the list of utilities
    df_util = get_df("utility.pkl")
    # Only keep the ones that are Active and not Test objects.
    df_util = df_util.query("Active == 1 and IsTestObject == 0").copy()
    # drop unneeded columns
    df_util.drop(columns=["Active", "IsTestObject", "NameShort"], inplace=True)

    # Retrieve the Fuel characteristics, modify into better format, and store in a DataFrame

    # Determine the directory where the local data files are located
    this_dir = os.path.dirname(os.path.realpath(__file__))
    data_dir = os.path.join(this_dir, "data")

    df_fuel = pd.read_excel(os.path.join(data_dir, "Fuel.xlsx"), index_col="id")
    df_fuel["btus"] = df_fuel.btus.astype(float)

    # Change the Efficiency choices column into a Python list (it is a string
    # right now.)
    df_fuel["effic_choices"] = df_fuel.effic_choices.apply(eval)

    # Apply Google Sheets overrides to utility rate data
    try:
        df_overrides = _fetch_gsheet_overrides()
        _apply_overrides(df_util, df_overrides)
        print(f"Applied {len(df_overrides)} utility rate overrides from Google Sheets.")
    except Exception as e:
        print(f"Warning: Failed to fetch/apply utility rate overrides: {e}")

    # Clear lru_caches since underlying data has changed
    city_from_id.cache_clear()
    util_from_id.cache_clear()
    fuel_from_id.cache_clear()
    fuel_price.cache_clear()


def periodically_refresh_data():
    """Function to periodically refresh the library data"""
    while True:
        try:
            refresh_data()
        except Exception as e:
            print(f'Error Refreshing Library Data: {e}')
        time.sleep(LIB_TIMEOUT * 3600.0)


# -----------------------------------------------

# These are the module-level variables that hold the key datasets.
# They are filled out via the refresh_data() routine below, which is called
# periodically so that any updates to the Internet-based datasets are
# reflected in the calculator.
# See documentation for these variables in the refresh_data() routine.
df_tmy_meta = None
df_city = None
df_util = None
df_fuel = None

# start a thread to refresh data periodically
thread = threading.Thread(target=periodically_refresh_data)
thread.daemon = True  # Daemon thread will exit when the main program exits
thread.start()
