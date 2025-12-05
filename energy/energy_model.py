"""Holds the class 'HomeHeatModel' that simulates the space heating
energy use of the home either with or without the heat pump.
"""

from typing import Tuple, List
from math import cos, pi

import numpy as np
from numpy.typing import NDArray
import pandas as pd

from .models import (
    BuildingDescription,
    HeatPumpSource,
    TimePeriodResults,
    DetailedModelResults,
    TemperatureTolerance,
    Fuel,
    EndUse
)
from library import library as lib
from library.models import Fuel_id
from general.utils import nan_to_none, dataframe_to_models, sum_dicts
from general.dict2d import Dict2d
from energy.heat_pump_performance import air_source_performance, ground_source_performance

# ----------- CONSTANTS

# Days in each month
DAYS_IN_MONTH = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])

GARAGE_HEATING_SETPT = 55.0  # deg F

# Amount of degrees that ground temperature is above annual average air temperature, deg F
GROUND_AIR_DELTA_T = 3.0

# Used to calculate peak electric demand in the month. Only has significance if there is
# a demand charge in the rate schedule. Since we are evalulating heat pumps, best to set
# this load factor to reflect the heat pumps contribution to coincident peak demand for
# the month. Then, electric cost impact of heat pump will be accurate, even though the
# reported peak demand for the whole home may not be accurate.
ELEC_LOAD_FACTOR = 0.3


def temp_depression(ua_per_ft2: float, balance_point: float, outdoor_temp: float, doors_open: bool) -> float:
    """Function returns the number of degrees F cooler that the bedrooms are
    relative to the main space, assuming no heating system heat is directly
    provided to bedrooms.  Bedrooms are assumed to be adjacent to the main
    space that is heated directly by a heating system.  This function can be
    used for other rooms that are adjacent to the main space and not directly
    heated.
    See https://github.com/alanmitchell/heat-pump-study/blob/master/general/bedroom_temp_depression.ipynb
    for derivation of the formula.
    'ua_per_ft2':  is the heat loss coefficient per square foot of floor area
        for the building.  It is measured as Btu/hour/deg-F/ft2
    'balance_point': is the balance point temperature (deg F) for the building; an outdoor
        temperature above which no heat needs to be supplied to the building.
    'outdoor_temp': the outdoor temperature, deg F.
    'doors_open': True if the doors between the main space and the bedroom are open,
        False if they are closed.
    """

    r_to_bedroom = 0.424 if doors_open else 1.42
    temp_delta = balance_point - outdoor_temp
    temp_depress = temp_delta * r_to_bedroom / (r_to_bedroom + 1.0 / ua_per_ft2)
    return temp_depress

def monthly_lights_apps(avg_kwh: float, frac_variation: float) -> NDArray[np.float64]:
    """
    Returns a numpy Array of 12 kWh values, January - December, representing the kWh used
    in each month for lights and miscellaneous electrical uses, not counting space heat,
    water heat, cooking and clothes drying. Assumes sinusoidal variation with the June
    and December being the min/max points on the curve. If 'frac_variation' is positive, June is
    minimum and December in maximum use; if 'frac_variation' is negative, shape is reversed.
    
    :param avg_kwh: annual average daily electrical consumption, kWh / day
    :param frac_variation: difference between use/day for the higest use month and annual average 
        use/day, expressed as a fraction of annual average use per day. Could be negative.
    """
    use_per_day = np.array([0.0] * 12)
    for mo in range(1, 13):
        radians = (mo % 12) / 12 * 2 * pi
        use_per_day[mo - 1] = avg_kwh + frac_variation * avg_kwh * cos(radians)

    return DAYS_IN_MONTH * use_per_day

# ---------------- Main Calculation Method --------------------

def model_building(inp: BuildingDescription) -> DetailedModelResults:
    """Main calculation routine that models the home and determines
    loads and fuel use by hour.  Also calculates summary results.
    """
    # Results dictionary
    res = {}

    # ------ Get information about city
    city = lib.city_from_id(inp.city_id)

    # ------ Make a DataFrame with hourly input information
    # Do as much processing at this level using array operations, as
    # opposed to processing within the hourly loop further below.

    tmy_site = lib.tmy_from_id(city.TMYid)
    df_tmy = pd.DataFrame(tmy_site.hourly_data)
    dfh = df_tmy[["db_temp", "month"]].copy()
    dfh["day_of_year"] = [i for i in range(1, 366) for _ in range(24)]

    if inp.heat_pump is not None:
        # Determine days that the heat pump is running.  Look at the 20th percentile
        # temperature for the day, and ensure that it is above the low
        # temperature cutoff.
        if inp.heat_pump.low_temp_cutoff is not None:
            hp_is_running = lambda x: (x.quantile(0.2) > inp.heat_pump.low_temp_cutoff)
            dfh["running"] = dfh.groupby("day_of_year")["db_temp"].transform(hp_is_running)
        else:
            # no cutoff, always running
            dfh["running"] = True

        # Also consider whether the user has selected the month as an Off month.
        if inp.heat_pump.off_months is not None:
            off_mask = dfh.month.isin(inp.heat_pump.off_months)
            dfh.loc[off_mask, "running"] = False

        # Get arrays that map outdoor air temperature to COP and to maximum heating capacity
        if inp.heat_pump.source_type == HeatPumpSource.air:
            temps, cops, max_capacities = air_source_performance(
                inp.heat_pump.hspf,
                inp.heat_pump.hspf_type,
                inp.heat_pump.cop_32f,
                inp.heat_pump.max_out_5f,
                inp.indoor_heat_setpoint
            )
        else:
            # estimate ground temperature from average annual air temperature and an offset.
            ground_temp = dfh.db_temp.mean() + GROUND_AIR_DELTA_T
            temps, cops, max_capacities = ground_source_performance(
                inp.heat_pump.cop_32f,
                inp.heat_pump.max_out_32f,
                inp.indoor_heat_setpoint,
                ground_temp
            )

        # Note that this same COP curve is used if the garage is heated by the heat pump
        # because heatpump condenser temperature will be set by the home indoor setpoint,
        # even though the garage runs at a cooler temperature

        dfh["cop"] = np.interp(dfh.db_temp, temps, cops)

        # Make an hourly array of maximum heat pump output, BTU/hour
        dfh["max_hp_output"] = np.interp(dfh.db_temp, temps, max_capacities)

    else:
        # No heat pump installed
        dfh["running"] = False
        dfh["cop"] = 1.0  # filler value
        dfh["max_hp_output"] = 0.0

    # The UA values below are Btu/hr/deg-F
    # Inputs provided UA / ft2 for the main home. We assume garage is 10% higher
    # due to higher air leakage.    
    ua_home = inp.ua_per_ft2 * inp.bldg_floor_area
    garage_area = (0, 14 * 22, 22 * 22, 36 * 25, 48 * 28)[inp.garage_stall_count]
    ua_garage = inp.ua_per_ft2 * 1.1 * garage_area

    # Balance Points of main home and garage
    # Assume a 8 deg F internal/solar heating effect for a UA/ft2 of 0.19
    # in the main home and a 4 deg F heating effect in the garage.
    # Adjust the heating effect accordingly for differing UA / ft2.
    balance_point_home = inp.indoor_heat_setpoint - 8.0 * 0.19 / inp.ua_per_ft2

    # fewer internal/solar in garage
    balance_point_garage = GARAGE_HEATING_SETPT - 4.0 * 0.19 / inp.ua_per_ft2

    # BTU loads in the hour for the heat pump and for the secondary system.
    hp_load = []
    conventional_load = []

    # More complicated calculations are done in this hourly loop.  If processing
    # time becomes a problem, try to convert the calculations below into array
    # operations that can be done outside the loop.

    hp_capacity_used = []  # fraction of heat pump capacity used in each hour

    for h in dfh.itertuples():
        # calculate total heat load for the hour.
        # Really need to recognize that delta-T to outdoors is lower in the adjacent and remote spaces
        # if there heat pump is the only source of heat. But, I'm saving that for later work.
        home_load = max(0.0, balance_point_home - h.db_temp) * ua_home
        garage_load = max(0.0, balance_point_garage - h.db_temp) * ua_garage
        total_load = home_load + garage_load
        if not h.running:
            hp_load.append(0.0)
            conventional_load.append(total_load)
            hp_capacity_used.append(0.0)
        else:
            # Build up the possible heat pump load, and then limit it to
            # maximum available from the heat pump.

            # Start with all of the load in the spaces exposed to heat pump indoor
            # units.
            hp_ld = home_load * inp.heat_pump.frac_exposed_to_hp

            # Then, garage load if it is heated by the heat pump
            hp_ld += garage_load * inp.heat_pump.serves_garage

            # For the spaces adjacent to the space heated directly by the heat pump,
            # first calculate how much cooler those spaces would be without direct
            # heat.
            temp_depress = temp_depression(
                inp.ua_per_ft2,
                balance_point_home,
                h.db_temp,
                inp.heat_pump.doors_open_to_adjacent,
            )
            # determine the temp depression tolerance in deg F
            temp_depress_tolerance = {
                TemperatureTolerance.low: 2.0,
                TemperatureTolerance.med: 5.0,
                TemperatureTolerance.high: 10.0,
            }[inp.heat_pump.bedroom_temp_tolerance]
            # if depression is less than this, include the load
            if temp_depress <= temp_depress_tolerance:
                # I'm not diminishing the load here for smaller delta-T.  It's possible
                # the same diminished delta-T was present in the base case (point-source
                # heating system).  Probably need to refine this.
                hp_ld += home_load * inp.heat_pump.frac_adjacent_to_hp

            # limit the heat pump load to its capacity at this temperature
            hp_ld = min(hp_ld, h.max_hp_output)

            hp_load.append(hp_ld)
            conventional_load.append(total_load - hp_ld)

            # record the fraction of the heat pump capacity being used.
            hp_capacity_used.append(hp_ld / h.max_hp_output)

    dfh["hp_load_mmbtu"] = np.array(hp_load) / 1e6
    dfh["conventional_load_mmbtu"] = np.array(conventional_load) / 1e6
    dfh["hp_capacity_used"] = hp_capacity_used

    # calculate heat pump kWh usage
    dfh["hp_kwh"] = dfh.hp_load_mmbtu / dfh.cop / 0.003412

    # Store annual and monthly totals.
    # Annual totals is a Pandas Series.
    total_cols = [
        "hp_load_mmbtu",
        "conventional_load_mmbtu",
        "hp_kwh",
    ]
    dfm = dfh.groupby("month")[total_cols].sum()

    # Add a column for the fraction of the total heat load served by the heat pump.
    dfm["hp_load_frac"] = dfm.hp_load_mmbtu / (
        dfm.hp_load_mmbtu + dfm.conventional_load_mmbtu
    )

    # Add a column for the fraction of heat pump capacity used, maximum across hours
    dfm["hp_capacity_used_max"] = dfh.groupby("month")[["hp_capacity_used"]].max()

    # COP by month
    dfm["cop"] = dfm.hp_load_mmbtu / (dfm.hp_kwh * 0.003412)

    # split conventional load across primary, secondary systems
    dfm["conventional_load_mmbtu_primary"] = inp.conventional_heat[0].frac_load_served * dfm.conventional_load_mmbtu
    dfm["conventional_load_mmbtu_secondary"] = inp.conventional_heat[1].frac_load_served * dfm.conventional_load_mmbtu

    # Loop across months to calculate fuel use by end use in each month
    fuel_use_mmbtu_all = []
    elec_demand_all = []
    fuel_use_units_all = []
    fuel_cost_all = []
    fuel_total_cost_all = []
    for row in dfm.itertuples():

        days_in_mo = DAYS_IN_MONTH[row.Index]

        # initialize data structures for this month
        fuel_use_mmbtu = Dict2d()
        fuel_use_units = Dict2d()
        fuel_cost = {}

        # heat pump electrical use
        fuel_use_mmbtu.add(Fuel_id.elec, EndUse.space_htg, row.hp_kwh * 0.003412)
        fuel_use_units.add(Fuel_id.elec, EndUse.space_htg, row.hp_kwh)

        # conventional heating systems
        for i in range(2):

            htg_sys = inp.conventional_heat[i]

            # get fuel information for this system
            fuel_id = htg_sys.heat_fuel_id
            fuel = lib.fuel_from_id(fuel_id)
            
            load_served = dfm.conventional_load_mmbtu_primary if i == 0 else dfm.conventional_load_mmbtu_secondary
            aux_kwh = load_served * inp.conventional_heat[i].aux_elec_use
            fuel_mmbtu = (load_served - aux_kwh * 0.003412) / htg_sys.heating_effic

            fuel_use_mmbtu.add(fuel_id, EndUse.space_htg, fuel_mmbtu)
            fuel_use_units.add(fuel_id, EndUse.space_htg, fuel_mmbtu * 1e6 / fuel.btus)
            fuel_use_mmbtu.add(Fuel_id.elec, EndUse.space_htg, aux_kwh * 0.003412)
            fuel_use_units.add(Fuel_id.elec, EndUse.space_htg, aux_kwh)

        # *********** DO OTHER END USES HERE *************

        # ************************************************

        # ***** CALCULATE FUEL COST by FUEL TYPE and TOTAL FUEL COST *****
        fuel_total_cost = 0.0

        fuel_use_mmbtu_all.append(fuel_use_mmbtu)
        fuel_use_units_all.append(fuel_use_units)
        fuel_cost_all.append(fuel_cost)
        fuel_total_cost_all.append(fuel_total_cost)

        # calculate peak electrical demand
        elec_kwh = fuel_use_units.sum_key1()[Fuel_id.elec]
        elec_demand_all.append(elec_kwh / days_in_mo / 24.0 / ELEC_LOAD_FACTOR)

    dfm['fuel_use_mmbtu'] = fuel_use_mmbtu_all
    dfm['elec_demand'] = elec_demand_all
    dfm['fuel_use_units'] = fuel_use_units_all
    dfm['fuel_cost'] = fuel_cost_all
    dfm['fuel_total_cost'] = fuel_total_cost_all

    # Add in a column to report the period being summarized
    dfm["period"] = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]

    # Aggregate monthly results into annual results
    tot = monthly_to_annual_results(dfm)

    # Include monthly and annual results
    res["monthly_results"] = dataframe_to_models(dfm, TimePeriodResults, True)
    res["annual_results"] = nan_to_none(tot.to_dict())

    # Calculate and record design heating load information
    design_t = tmy_site.site_info.heating_design_temp
    res["design_heat_temp"] = design_t
    res["design_heat_load"] = ua_home * (
        inp.indoor_heat_setpoint - design_t
    ) + ua_garage * (GARAGE_HEATING_SETPT - design_t)

    return DetailedModelResults(**res)

def monthly_to_annual_results(df_monthly: pd.DataFrame) -> pd.Series:
    """Aggregrates a monthly model results DataFrame (with columns that are all
    or a subset of TimePeriodResults) into an Annual Pandas series.
    """
    # Make a list of the columms to sum.
    sum_cols = [
        'hp_load_mmbtu',
        'hp_kwh',
        'conventional_load_mmbtu',
        'conventional_load_mmbtu_primary',
        'conventional_load_mmbtu_secondary',
        'fuel_total_cost'
    ]
    annual = df_monthly[sum_cols].sum()

    # columns to take the max of
    max_cols = ['hp_capacity_used_max', 'elec_demand']
    for col in max_cols:
        annual[col] = df_monthly[col].max()

    annual["hp_load_frac"] = annual.hp_load_mmbtu / (
            annual.hp_load_mmbtu + annual.conventional_load_mmbtu
        )

    # calculate annual COP of the heat pump, if present
    if annual.hp_kwh > 0.0:
        annual["cop"] = annual.hp_load_mmbtu / (annual.hp_kwh * 0.003412)
    else:
        annual["cop"] = np.nan

    # loop the months to sum up Dict2d objects
    fuel_use_mmbtu = Dict2d()
    fuel_use_units = Dict2d()
    for row in df_monthly.itertuples():
        fuel_use_mmbtu.add_object(row.fuel_use_mmbtu)
        fuel_use_units.add_object(row.fuel_use_units)
    annual['fuel_use_mmbtu'] = fuel_use_mmbtu
    annual['fuel_use_units'] = fuel_use_units

    # fuel cost dictionary by fuel type
    annual['fuel_cost'] = sum_dicts(df_monthly.fuel_cost.values())

    # add the period column back in
    annual["period"] = "Annual"

    return annual
