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
    HeatPumpWaterHeaterSource,
    TimePeriodResults,
    DetailedModelResults,
    TemperatureTolerance,
    EndUse
)
from .heat_pump_performance import air_source_performance, ground_source_performance

from library import library as lib
from library.models import Fuel_id
from general.utils import nan_to_none, dataframe_to_models, sum_dicts, chg_nonnum, chg_none_nan
from general.dict2d import Dict2d
from econ.elec_cost import ElecCostCalc

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
ELEC_LOAD_FACTOR = 0.35


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

def seasonal_use(avg_use_per_day: float, frac_variation: float) -> NDArray[np.float64]:
    """
    Returns a numpy Array of 12 kWh values, January - December, representing the total 
    energy use in each month given a specified amount of seasonal variaon.
    Assumes sinusoidal variation with the June and December being the min/max points on the 
    curve. If 'frac_variation' is positive, June is minimum and December in maximum use;
    if 'frac_variation' is negative, shape is reversed.
    
    :param avg_use_per_day: annual average energy use / day in any units
    :param frac_variation: difference between use/day for the higest use month and annual average 
        use/day, expressed as a fraction of annual average use per day. Could be negative.

    The return array has values with the same units as 'avg_use_per_day'.
    """
    use_per_day = np.array([0.0] * 12)
    for mo in range(1, 13):
        radians = (mo % 12) / 12 * 2 * pi
        use_per_day[mo - 1] = avg_use_per_day + frac_variation * avg_use_per_day * cos(radians)

    return DAYS_IN_MONTH * use_per_day

def monthly_solar(avg_production_per_day: float) -> NDArray[np.float64]:
    """Returns monthly kWh production from a solar array having an average per day production
    of 'avg_production_per_day'. The return value is a 12-element Numpy array.

    *** Note that this is tuned for Southeast Alaska. If use of the model is broadened, the pattern
    below could be a function of the location or latitude of the building, and not just frozen to one 
    pattern.
    """
    # the production pattern below was developed from a PVWatts run for Juneau,
    # due South array tilted at 30 degrees.
    pattern = np.array([0.283, 0.624, 1.005, 1.521, 2.131, 1.738, 1.451, 1.366, 0.753, 0.500, 0.386, 0.220])
    return pattern * avg_production_per_day * DAYS_IN_MONTH

# ---------------- Main Calculation Method --------------------

# @profile
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
    dfh = lib.tmy_df_from_id(city.TMYid)

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

    # Determine domestic hotwater load per day, based on number of occupants.
    # Used an AkWarm run to determin DHW load per person at the 3 occupant level
    if inp.dhw_fuel_id is not None:
        dhw_mmbtu_load_per_day = 4.23 * inp.occupant_count / 365.0
    else:
        dhw_mmbtu_load_per_day = 0.0

    # If this is a heat pump water heater (as indicated by fuel type and EF > 1),
    # determine how much space heating load is created per day due to possible heat 
    # extraction from the building. Express as BTU / day of space heating load.
    garage_hpwh_load = 0.0
    main_home_hpwh_load = 0.0
    if inp.dhw_fuel_id == Fuel_id.elec and inp.dhw_ef > 1.0:
        match inp.dhw_hpwh_source:
            case HeatPumpWaterHeaterSource.garage:
                garage_hpwh_load = dhw_mmbtu_load_per_day * (inp.dhw_ef - 1.0) / inp.dhw_ef * 1e6
                main_home_hpwh_load = 0.0

            case HeatPumpWaterHeaterSource.main_home:
                garage_hpwh_load = 0.0
                main_home_hpwh_load = dhw_mmbtu_load_per_day * (inp.dhw_ef - 1.0) / inp.dhw_ef * 1e6

    if inp.heat_pump is None:
        # No heat pump, so many of the columns are simple and fast to calculate.
        # Important to be fast here because this code is executed many times when attempting
        # to fit the energy model.
        home_load = np.maximum(0.0, balance_point_home - dfh.db_temp.values) * ua_home
        home_load += main_home_hpwh_load / 24.0    # simplifying assumption: even spread across hours
        garage_load = np.maximum(0.0, balance_point_garage - dfh.db_temp.values) * ua_garage
        garage_load += garage_hpwh_load / 24.0

        dfh["conventional_load_mmbtu"] = (home_load + garage_load) / 1e6
        dfh["hp_load_mmbtu"] = 0.0
        dfh["hp_capacity_used"] = 0.0
        dfh["hp_kwh"] = 0.0

    else:
        # There is a heat pump and forced to due hourly calculations in a loop.

        # BTU loads in the hour for the heat pump and for the secondary system.
        hp_load = []
        conventional_load = []
        hp_capacity_used = []  # fraction of heat pump capacity used in each hour

        for h in dfh.itertuples():
            # calculate total heat load for the hour.
            # Really need to recognize that delta-T to outdoors is lower in the adjacent and remote spaces
            # if there heat pump is the only source of heat. But, I'm saving that for later work.
            home_load = max(0.0, balance_point_home - h.db_temp) * ua_home
            home_load += main_home_hpwh_load / 24.0    # simplifying assumption: even spread across hours
            garage_load = max(0.0, balance_point_garage - h.db_temp) * ua_garage
            garage_load += garage_hpwh_load / 24.0
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
        dfh["hp_capacity_used"] = np.array(hp_capacity_used)

        # calculate heat pump kWh usage
        dfh["hp_kwh"] = dfh.hp_load_mmbtu / dfh.cop / 0.003412

    # Create a monthly summary of the above values.
    # Do array math to produce as much as possible.
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

    # --------------------- MONTHLY LOOP ---------------------------
    # Loop across months to calculate fuel use by end use in each month. Build up arrays
    # of monthly values to be later added to the results DataFrame.
    fuel_use_mmbtu_all = []
    elec_demand_all = []
    fuel_use_units_all = []
    fuel_cost_all = []
    fuel_total_cost_all = []
    co2_all = []

    # Prepare some values and objects that are fixed across all months

    prices = inp.energy_prices     # shortcut variable

    # determine sales tax, which applies to fuel prices and electric utility
    # rates.
    if prices.sales_tax_override is not None:
        sales_tax = chg_nonnum(prices.sales_tax_override, 0.0)
    else:
        sales_tax = chg_nonnum(city.BoroughSalesTax, 0.0) + chg_nonnum(city.MunicipalSalesTax, 0.0)

    # Get the electric utility cost object
    elec_util = lib.util_from_id(prices.utility_id)

    # Some of the fields in the electric utility object may be overridden.
    # Adjust the object now.
    if prices.elec_rate_override is not None:
        # overwrite the block structure with one block
        elec_util.Blocks = [(None, prices.elec_rate_override)]
        # zero out the demand charge as that is included in the overridden electric rate.
        elec_util.DemandCharge = 0.0
    if prices.pce_rate_override is not None:
        elec_util.PCE = prices.pce_rate_override
    if prices.customer_charge_override is not None:
        elec_util.CustomerChg = prices.customer_charge_override
    if prices.co2_lbs_per_kwh_override is not None:
        elec_util.CO2 = prices.co2_lbs_per_kwh_override

    # Create the object that does the actual electric utility cost calculations
    elec_cost_calc = ElecCostCalc(
        elec_util, sales_tax=sales_tax, pce_limit=prices.pce_limit
    )

    # Create a dictionary keyed on fuel type that gives the fuel price
    # accounting for user overrides and sales tax. Only create for the fuels used in this
    # building, except electricity
    fuels_used = set([
        inp.conventional_heat[0].heat_fuel_id,
        inp.conventional_heat[1].heat_fuel_id,
        inp.dhw_fuel_id,
        inp.clothes_drying_fuel_id,
        inp.cooking_fuel_id
        ])
    # None may be in the set if some of these uses are not present. Remove the None
    if None in fuels_used:
        fuels_used.remove(None)

    fuel_price = {}
    for fuel_id in fuels_used:
        if fuel_id != Fuel_id.elec and fuel_id is not None:
            if fuel_id in prices.fuel_price_overrides:
                fuel_price[fuel_id] = prices.fuel_price_overrides[fuel_id] * (1.0 + sales_tax)
            else:
                fuel_info = lib.fuel_from_id(fuel_id)
                price = chg_none_nan(getattr(city, fuel_info.price_col))
                fuel_price[fuel_id] = price * (1.0 + sales_tax)

    # -- DHW per day
    if inp.dhw_fuel_id is not None:
        dhw_mmbtu_per_day = dhw_mmbtu_load_per_day / inp.dhw_ef
        fuel = lib.fuel_from_id(inp.dhw_fuel_id)
        dhw_units_per_day = dhw_mmbtu_per_day * 1e6 / fuel.btus
    else:
        dhw_mmbtu_per_day = 0.0

    # -- Clothes Drying
    if inp.clothes_drying_fuel_id is not None:
        drying_mmbtu_per_day = (0.86 if inp.clothes_drying_fuel_id == Fuel_id.elec else 2.15) * inp.occupant_count / 365.0
        fuel = lib.fuel_from_id(inp.clothes_drying_fuel_id)
        drying_units_per_day = drying_mmbtu_per_day * 1e6 / fuel.btus
    else:
        drying_mmbtu_per_day = 0.0

    # -- Cooking per day
    if inp.cooking_fuel_id is not None:
        cooking_mmbtu_per_day = (0.64 if inp.cooking_fuel_id == Fuel_id.elec else 0.8) * inp.occupant_count / 365.0
        fuel = lib.fuel_from_id(inp.cooking_fuel_id)
        cooking_units_per_day = cooking_mmbtu_per_day * 1e6 / fuel.btus
    else:
        cooking_mmbtu_per_day = 0.0

    # -- Lights / Misc. Appliances electric use
    # get an array of Lights/Misc. Appliances electric use values in kWh
    misc_elec_kwh_by_month = seasonal_use(inp.misc_elec_kwh_per_day, inp.misc_elec_seasonality)

    # -- EV Charging electric use
    ev_kwh_by_month = seasonal_use(
        inp.ev_charging_miles_per_day / inp.ev_miles_per_kwh,
        inp.ev_seasonality
        )
    
    # -- Solar Production. Included as a negative energy end use.
    solar_kwh_by_month = monthly_solar(inp.solar_kw * inp.solar_kwh_per_kw / 365.0)

    for row in dfm.itertuples():

        days_in_mo = DAYS_IN_MONTH[row.Index - 1]

        # initialize data structures for this month
        fuel_use_mmbtu = Dict2d()
        fuel_use_units = Dict2d()

        # heat pump electrical use
        fuel_use_mmbtu.add(Fuel_id.elec, EndUse.space_htg, row.hp_kwh * 0.003412)
        fuel_use_units.add(Fuel_id.elec, EndUse.space_htg, row.hp_kwh)

        # conventional heating systems
        for i in range(2):

            htg_sys = inp.conventional_heat[i]

            # get fuel information for this system
            fuel_id = htg_sys.heat_fuel_id
            if fuel_id is not None:
                fuel = lib.fuel_from_id(fuel_id)
                
                load_served = row.conventional_load_mmbtu_primary if i == 0 else row.conventional_load_mmbtu_secondary
                aux_kwh = load_served * inp.conventional_heat[i].aux_elec_use
                fuel_mmbtu = (load_served - aux_kwh * 0.003412) / htg_sys.heating_effic

                fuel_use_mmbtu.add(fuel_id, EndUse.space_htg, fuel_mmbtu)
                fuel_use_units.add(fuel_id, EndUse.space_htg, fuel_mmbtu * 1e6 / fuel.btus)
                fuel_use_mmbtu.add(Fuel_id.elec, EndUse.space_htg, aux_kwh * 0.003412)
                fuel_use_units.add(Fuel_id.elec, EndUse.space_htg, aux_kwh)

        # ---- Other End Uses

        # DHW
        if dhw_mmbtu_per_day:
            fuel_use_mmbtu.add(inp.dhw_fuel_id, EndUse.dhw, dhw_mmbtu_per_day * days_in_mo)
            fuel_use_units.add(inp.dhw_fuel_id, EndUse.dhw, dhw_units_per_day * days_in_mo)

        # Clothes Drying
        if drying_mmbtu_per_day:
            fuel_use_mmbtu.add(inp.clothes_drying_fuel_id, EndUse.drying, drying_mmbtu_per_day * days_in_mo)
            fuel_use_units.add(inp.clothes_drying_fuel_id, EndUse.drying, drying_units_per_day * days_in_mo)

        # Cooking
        if cooking_mmbtu_per_day:
            fuel_use_mmbtu.add(inp.cooking_fuel_id, EndUse.cooking, cooking_mmbtu_per_day * days_in_mo)
            fuel_use_units.add(inp.cooking_fuel_id, EndUse.cooking, cooking_units_per_day * days_in_mo)

        # Lights/Misc Appliance Electric use
        kwh = misc_elec_kwh_by_month[row.Index - 1]
        fuel_use_mmbtu.add(Fuel_id.elec, EndUse.misc_elec, kwh * 0.003412)
        fuel_use_units.add(Fuel_id.elec, EndUse.misc_elec, kwh)

        # Home EV Charging
        kwh = ev_kwh_by_month[row.Index - 1]
        fuel_use_mmbtu.add(Fuel_id.elec, EndUse.ev_charging, kwh * 0.003412)
        fuel_use_units.add(Fuel_id.elec, EndUse.ev_charging, kwh)

        # Solar PV pdroduction
        kwh = solar_kwh_by_month[row.Index - 1]
        fuel_use_mmbtu.add(Fuel_id.elec, EndUse.pv_solar, -kwh * 0.003412)
        fuel_use_units.add(Fuel_id.elec, EndUse.pv_solar, -kwh)

        # ---- Calculate fuel cost

        # Structure to hold fuel cost by type of fuel
        fuel_cost_by_type = {}

        # Tracks total fuel cost
        fuel_total_cost = 0.0

        # Get the sum of the fuel use in fuel units across fuel types
        fuel_use_by_fuel_type = fuel_use_units.sum_key1()

        # determine electrical peak demand
        # (should always be some electric use, but just in case)
        if Fuel_id.elec in fuel_use_by_fuel_type:
            peak_demand = fuel_use_by_fuel_type[Fuel_id.elec] / days_in_mo / 24.0 / ELEC_LOAD_FACTOR
        else:
            peak_demand = 0.0
        elec_demand_all.append(peak_demand)

        # Loop across fuel use by fuel type
        for fuel_id, fuel_use in fuel_use_by_fuel_type.items():

            if fuel_id == Fuel_id.elec:
                # electricity is special case; need to use electric utility rate structure
                # to determine fuel use
                elec_cost = elec_cost_calc.monthly_cost(fuel_use, peak_demand)
                fuel_cost_by_type[Fuel_id.elec] = elec_cost
                fuel_total_cost += elec_cost

            else:
                cost = fuel_use * fuel_price[fuel_id]
                fuel_cost_by_type[fuel_id] = cost
                fuel_total_cost += cost

        # ----- Calculate CO2 emissions

        # Tracks CO2 pounds of emissions
        co2_lbs = 0.0

        # fuel MMBTU by fuel type
        fuel_mmbtu_by_type = fuel_use_mmbtu.sum_key1()
        for fuel_id, mmbtu in fuel_mmbtu_by_type.items():

            if fuel_id == Fuel_id.elec:
                co2_lbs += mmbtu / 0.003412 * elec_util.CO2

            else:
                fuel_info = lib.fuel_from_id(fuel_id)
                co2_lbs += mmbtu * fuel_info.co2


        # ---- Add to the arrays tracking monthly values
        fuel_use_mmbtu_all.append(fuel_use_mmbtu.get_all())
        fuel_use_units_all.append(fuel_use_units.get_all())
        fuel_cost_all.append(fuel_cost_by_type)
        fuel_total_cost_all.append(fuel_total_cost)
        co2_all.append(co2_lbs)

    dfm['fuel_use_mmbtu'] = fuel_use_mmbtu_all
    dfm['elec_demand'] = elec_demand_all
    dfm['fuel_use_units'] = fuel_use_units_all
    dfm['fuel_cost'] = fuel_cost_all
    dfm['fuel_total_cost'] = fuel_total_cost_all
    dfm['co2_lbs'] = co2_all

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
    tmy_site = lib.tmy_from_id(city.TMYid, True)
    design_t = tmy_site.site_info.heating_design_temp
    res["design_heat_temp"] = design_t
    res["design_heat_load"] = ua_home * (
        inp.indoor_heat_setpoint - design_t
    ) + ua_garage * (GARAGE_HEATING_SETPT - design_t)

    return DetailedModelResults(**res)

# @profile
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
        'fuel_total_cost',
        'co2_lbs'
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
        fuel_use_mmbtu.add_object(Dict2d(row.fuel_use_mmbtu))
        fuel_use_units.add_object(Dict2d(row.fuel_use_units))
    annual['fuel_use_mmbtu'] = fuel_use_mmbtu.get_all()
    annual['fuel_use_units'] = fuel_use_units.get_all()

    # fuel cost dictionary by fuel type
    annual['fuel_cost'] = sum_dicts(df_monthly.fuel_cost.values)

    # add the period column back in
    annual["period"] = "Annual"

    return annual
