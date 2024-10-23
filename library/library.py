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

import pandas as pd
import requests

from general.models import Choice
from general.utils import NaNtoNone
from library.models import (
    City, 
    Utility, 
    Fuel, 
    FuelPrice, 
    TMYmeta, 
    TMYhourlyRec, 
    TMYdataset
)

# Most of the data files are located remotely and are retrieved via
# an HTTP request.  The function below is used to retrieve the files,
# which are Pandas DataFrames

# The base URL to the site where the remote files are located
base_url = 'https://github.com/alanmitchell/akwlib-export/raw/main/data/v01/'

# This constant controls how frequently the library goes back to the GitHub server to
# download the freshest AkWarm data.  This timeout is only checked when the heat_pump_from_id()
# function below is called.
LIB_TIMEOUT = 12     # units are Hours

# this variable tracks the last time the Akwarm data was refreshed
last_lib_download_ts = 0.0        # Unix timestamp

def get_df(file_path):
    """Returns a Pandas DataFrame that is found at the 'file_path'
    below the Base URL for accessing data.  The 'file_path' should end
    with '.pkl' and points to a pickled, compressed (bz2), Pandas DataFrame.
    """
    b = requests.get(urllib.parse.urljoin(base_url, file_path)).content
    df = pd.read_pickle(io.BytesIO(b), compression='bz2')
    return df

# -----------------------------------------------------------------
# Functions to provide the library data to the rest of the
# application.
def cities() -> List[Choice]:
    """List of all (city name, city ID), alphabetically sorted.  
    """
    city_list = list(zip(df_city.Name, df_city.index))
    city_list.sort()   # sorts in place; returns None
    return [Choice(label=label, id=id) for label, id in city_list]

def city_from_id(city_id) -> City:
    """Returns a dictionary containing the city information for the City
    identified by 'city_id'. 
    """
    city_dict = df_city.loc[city_id].to_dict()
    # turn utility list into list of Choice items
    city_dict['ElecUtilities'] = [{'label': label, 'id': id} for label, id in city_dict['ElecUtilities']]
    # do the following to replace NaN's with None
    city_dict = NaNtoNone(city_dict)
    city_dict['id'] = city_id
    return City(**city_dict)

# --------------------------------------------------------------------------------------

def utilities() -> List[Choice]:
    """List of all utility rate structures, sorted by utility rate name.
    """
    util_list =  list(zip(df_util.Name, df_util.index))
    util_list.sort()
    return [Choice(label=label, id=id) for label, id in util_list]

def util_from_id(util_id) -> Utility:
    """Returns a dictionary containing all of the Utility information for
    the Utility identified by util_id.
    """
    return_dict = NaNtoNone(df_util.loc[util_id].to_dict())
    return_dict['id'] = util_id
    return Utility(**return_dict)

# --------------------------------------------------------------------------------------

def fuels() -> List[Choice]:
    """Returns a list of fuel names and IDs.
    """
    fuel_list = list(zip(df_fuel.desc, df_fuel.index))
    return [Choice(label=label, id=id) for label, id in fuel_list]

def fuel_from_id(fuel_id) -> Fuel:
    """Returns fuel information for the fuel with
    and ID of 'fuel_id'
    """
    fuel_dict = NaNtoNone(df_fuel.loc[fuel_id].to_dict())
    fuel_dict['id'] = fuel_id
    return Fuel(**fuel_dict)

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

    return_dict = NaNtoNone({'city': city_name, 'fuel': fuel_name, 'price': price})
    return FuelPrice(**return_dict)

# --------------------------------------------------------------------------------------

def tmys() -> List[TMYmeta]:
    """Returns a list of available TMY sites and associated info.
    """
    return [TMYmeta(**rec) for rec in df_tmy_meta.reset_index().to_dict(orient='records')]

@functools.lru_cache(maxsize=50)    # caches the TMY dataframes cuz retrieved remotely
def tmy_from_id(tmy_id, site_info_only=False) -> TMYdataset:
    """Returns a list of TMY hourly records and meta data for the climate site identified
    by 'tmy_id'.
    """
    site_info = TMYmeta(tmy_id=tmy_id, **df_tmy_meta.loc[tmy_id].to_dict())
    if not site_info_only:
        df_records = get_df(f'tmy3/{tmy_id}.pkl')
        df_records['hour'] = list(range(0, 24)) * 365
        recs = [TMYhourlyRec(**rec) for rec in df_records.to_dict(orient='records')]
        return TMYdataset(site_info=site_info, records=recs)
    else:
        return TMYdataset(site_info=site_info)

# --------------------------------------------------------------------------------------

def refresh_data():
    """Key datasets are read in here and placed in module-level variables,
    listed below this function.
    """
    global df_tmy_meta
    global df_city
    global df_util
    global df_fuel
    global last_lib_download_ts        # tracks time of last refresh

    print('acquiring library data...')
    last_lib_download_ts = time.time()

    # Key datasets are read in here and are available as module-level
    # variables for use in the functions above.

    # read in the DataFrame that describes the available TMY3 climate files.
    df_tmy_meta = get_df('tmy3/tmy3_meta.pkl')

    # Read in the other City and Utility Excel files.
    df_city = get_df('city.pkl')
    # Need to add an empty column for the price of Wood Pellets
    df_city['WoodPelletsPrice'] = float('nan')

    # Retrive the list of utilities
    df_util = get_df('utility.pkl')
    # Only keep the ones that are Active and not Test objects.
    df_util = df_util.query('Active == 1 and IsTestObject == 0').copy()
    # drop unneeded columns
    df_util.drop(columns=['Active', 'IsTestObject', 'NameShort'], inplace=True)

    # Retrieve the Fuel characteristics, modify into better format, and store in a DataFrame

    # Determine the directory where the local data files are located
    this_dir = os.path.dirname(os.path.realpath(__file__))
    data_dir = os.path.join(this_dir, 'data')

    df_fuel = pd.read_excel(os.path.join(data_dir, 'Fuel.xlsx'), index_col='id')
    df_fuel['btus'] = df_fuel.btus.astype(float)

    # Change the Efficiency choices column into a Python list (it is a string
    # right now.)
    df_fuel['effic_choices'] = df_fuel.effic_choices.apply(eval)

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

# fill out the data variables
refresh_data()
