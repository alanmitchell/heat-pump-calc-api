"""Models related to the Library.
"""
from typing import List, Tuple, Optional, Dict
from pydantic import BaseModel

from general.models import Choice

class City(BaseModel):
    """Information about one city.
    """
    id: int                              # ID of this City
    Name: str                            # City name
    Latitude: float                      # Latitude, decimal degrees
    Longitude: float                     # Longitude, decimal degrees
    ERHRegionID: int                     # Energy Rated Homes Region ID
    WAPRegionID: int                     # Weatherization Region ID
    ImprovementCostLevel: int            # 1 - 5, 1 is low cost, e.g. Anchorage
    FuelRefer: bool                      # True if this city is tied to a different city for fuel prices
    FuelCityID: int | None               # If FuelRefer, ID of the city used for fuel prices
    Oil1Price: float | None              # $/gallon for #1 Heating Oil
    Oil2Price: float | None              # $/gallon for #2 Heating Oil
    PropanePrice: float | None           # $/gallon for propane
    BirchPrice: float | None             # $/cord for Birch wood
    SprucePrice: float | None            # $/cord for Spruce wood
    CoalPrice: float | None              # $/ton for Coal
    SteamPrice: float | None             # $/thousand-pounds for District Steam
    HotWaterPrice: float | None          # $/million-BTU for District Hot Water       
    WoodPelletsPrice: float | None       # $/ton of Wood pellets
    MunicipalSalesTax: float | None      # Municipal sales tax as fraction, e.g. 0.06 means 6%
    BoroughSalesTax: float | None        # Borough sales tax as fraction, e.g. 0.06 means 6%
    TMYid: int                           # Typical Meterological Year (TMY) ID of nearest TMY site
    TMYname: str                         # Name of nearest TMY site
    ElecUtilities: List[Choice]          # list of Electric utility rate structures available
    GasPrice: float | None               # Natural Gas price in $ / therm
    aris_city: str                       # ARIS database city name
    census_city: str                     # Census city name
    census_area: str                     # Census area
    ancsa_region: str                    # ANCSA region
    railbelt: str                        # 'Railbelt' if city is in Railbelt, otherwise 'Affordable Energy Strategy Area'
    hub: bool                            # True if a regional hub city
    avg_elec_usage: List[float] = [0.0] * 12   # 12-item array of average residential kWh usage for each month

class Utility(BaseModel):
    """Electric Utility Rate Structure Information"""
    id: int                              # ID of this utility rate schedule
    Name: str                            # Name of the rate schedule
    Type: int                            # 1 = Electricity, 2 = Natural Gas
    IsCommercial: bool                   # True if Commercial rate structure, False if Residential
    ChargesRCC: bool                     # True if utility collects the Alaska RCC Regulatory surcharge
    PCE: float | None                    # Alaska PCE $/kWh assistance
    CO2: float | None                    # pound-CO2/kWh for electric rate structures
    CustomerChg: float | None            # $/month customer charge
    DemandCharge: float | None           # $/kW/month demand charge
    Blocks: List[Tuple[float | None, float | None]]   # Array of (kWh block limit, $/kWh for block) for all rate blocks
                                                      #    Last block has None for block limit.

class Fuel(BaseModel):
    id: int                           # ID of this fuel type
    desc: str                         # Name of fuel
    unit: str                         # Measurement unit of fuel, e.g. 'gallon'
    btus: float                       # BTUs per unit of fuel
    co2: float | None                 # Pounds of CO2 per million BTU of fuel
    price_col: str | None             # Name of column in City model that contains the price per unit of this fuel in that City
    dhw_effic: float                  # Average efficiency of a domestic hot water system burning that fuel
    effic_choices: List[Tuple[str, float]]  # Array of (space heating system type, efficiency) for this fuel type
                                            #     efficiency is expressed as percentage, e.g. 75.0

class FuelPrice(BaseModel):
    """A price for a particular fuel in a particular city.
    """
    city: str                   # ID of city
    fuel: str                   # ID of fuel
    price: float | None         # $/unit for this fuel in the specified city

class TMYmeta(BaseModel):
    """Description of TMY site with summary stats"""
    tmy_id: int               # TMY ID of the site
    city: str                 # Site name
    state: str                # State
    utc_offset: float         # Hours of offset from UTC time for this site
    latitude: float           # latitude, decimal degrees
    longitude: float          # longitude, decimal degrees
    elevation: float          # elevation in feet of the site
    db_temp_avg: float        # annual average dry-bulb temperature, deg F
    rh_avg: float             # annual average relative humidity, expressed as percent 0 - 100
    wind_spd_avg: float       # annual avcerage wind speed, miles per hour
    heating_design_temp: float  # 99% heating design temperature, deg F

class TMYdataset(BaseModel):
    site_info: TMYmeta    # site information, see TMYmeta definition
    hourly_data: Dict[str, List[float | int]] | None = None     # dictionary of hourly data, keys are column names

