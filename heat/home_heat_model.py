"""Holds the class 'HomeHeatModel' that simulates the space heating
energy use of the home either with or without the heat pump.
"""

from typing import Tuple

import numpy as np
import pandas as pd

from .models import (
    HeatModelInputs,
    HeatPumpSource,
    TimePeriodResults,
    DetailedModelResults,
    WallInsulLevel,
    TemperatureTolerance,
)
from library import library as lib
from general.utils import nan_to_none, dataframe_to_models
from heat.heat_pump_performance import air_source_performance, ground_source_performance

# ----------- CONSTANTS

ELECTRIC_ID = 1  # The fuel ID for Electricity

GARAGE_HEATING_SETPT = 55.0  # deg F

# Amount of degrees that ground temperature is above annual average air temperature, deg F
GROUND_AIR_DELTA_T = 3.0    


def temp_depression(ua_per_ft2, balance_point, outdoor_temp, doors_open):
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


def design_heat_load(self) -> Tuple[float, float]:
    """Returns the 99% design heat load for the building and the associated
    design temperature, including the garage if present.  Do not account for
    any internal or solar gains, as is conventional.
    Return values are Btu/hour and deg F.
    """
    # get the 1% outdoor temperature
    design_temp = lib.heating_design_temp(self.city.TMYid)
    design_load = self.ua_home * (
        self.indoor_heat_setpoint - design_temp
    ) + self.ua_garage * (GARAGE_HEATING_SETPT - design_temp)
    return design_load, design_temp


# ---------------- Main Calculation Method --------------------


def model_space_heat(inp: HeatModelInputs) -> DetailedModelResults:
    """Main calculation routine that models the home and determines
    loads and fuel use by hour.  Also calculates summary results.
    """
    # Results dictionary
    res = {}

    # ------ create important input objects
    city = lib.city_from_id(inp.city_id)
    exist_heat_fuel = lib.fuel_from_id(inp.exist_heat_system.heat_fuel_id)

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
        
        # breakpoint()

    else:
        # No heat pump installed
        dfh["running"] = False
        dfh["cop"] = 1.0  # filler value
        dfh["max_hp_output"] = 0.0

    # adjustment to UA for insulation level.  My estimate, accounting
    # for better insulation *and* air-tightness as you move up the
    # insulation scale.
    insul_to_ua_adj = {
        WallInsulLevel.wall2x4: 1.25,
        WallInsulLevel.wall2x6: 1.0,
        WallInsulLevel.wall2x6plus: 0.75,
    }

    ua_insul_adj = insul_to_ua_adj[inp.insul_level]  # pick the appropriate one

    # The UA values below are Btu/hr/deg-F
    # This is the UA / ft2 of the ua_insul_adj = 1.0 home
    # for the main living space.  Assume garage UA is about 10% higher
    # due to higher air leakage.
    # Determined this UA/ft2 below by modeling a typical Enstar home
    # and having the model estimate space heating use of about 1250 CCF.
    # See 'accessible_UA.ipynb'.
    ua_per_ft2 = 0.189
    ua_home = ua_per_ft2 * ua_insul_adj * inp.bldg_floor_area * inp.ua_true_up
    garage_area = (0, 14 * 22, 22 * 22, 36 * 25, 48 * 28)[inp.garage_stall_count]
    ua_garage = ua_per_ft2 * 1.1 * ua_insul_adj * garage_area * inp.ua_true_up

    # Balance Points of main home and garage
    # Assume a 10 deg F internal/solar heating effect for Level 2 insulation
    # in the main home and a 5 deg F heating effect in the garage.
    # Adjust the heating effect accordingly for other levels of insulation.
    balance_point_home = inp.indoor_heat_setpoint - 10.0 / ua_insul_adj / inp.ua_true_up

    # fewer internal/solar in garage
    balance_point_garage = GARAGE_HEATING_SETPT - 5.0 / ua_insul_adj / inp.ua_true_up

    # BTU loads in the hour for the heat pump and for the secondary system.
    hp_load = []
    secondary_load = []

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
            secondary_load.append(total_load)
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
                ua_home / inp.bldg_floor_area,
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
            secondary_load.append(total_load - hp_ld)

            # record the fraction of the heat pump capacity being used.
            hp_capacity_used.append(hp_ld / h.max_hp_output)

    dfh["hp_load_mmbtu"] = np.array(hp_load) / 1e6
    dfh["secondary_load_mmbtu"] = np.array(secondary_load) / 1e6
    dfh["hp_capacity_used"] = hp_capacity_used

    # reduce the secondary load to account for the heat produced by
    # the auxiliary electricity use.
    # convert the auxiliary heat factor for the secondary heating system into an
    # energy ratio of aux electricity energy to heat delivered.
    aux_ratio = inp.exist_heat_system.aux_elec_use * 0.003412
    dfh["secondary_load_mmbtu"] /= 1.0 + aux_ratio

    # using array operations, calculate kWh use by the heat pump and
    # the Btu use of secondary system.
    dfh["hp_kwh"] = dfh.hp_load_mmbtu / dfh.cop / 0.003412
    dfh["secondary_fuel_mmbtu"] = (
        dfh.secondary_load_mmbtu / inp.exist_heat_system.heating_effic
    )
    dfh["secondary_kwh"] = (
        dfh.secondary_load_mmbtu * inp.exist_heat_system.aux_elec_use
    )  # auxiliary electric use

    # if this is electric heat as the secondary fuel, move the secondary fuel use into
    # the secondary kWh column and blank out the secondary fuel MMBtu.
    if inp.exist_heat_system.heat_fuel_id == ELECTRIC_ID:
        dfh.secondary_kwh += dfh.secondary_fuel_mmbtu * 1e6 / exist_heat_fuel.btus
        dfh["secondary_fuel_mmbtu"] = 0.0

    # Make a column for total kWh.  Do this at the hourly level because it is
    # needed to accurately account for coincident peak demand.
    dfh["space_heat_kwh"] = dfh.hp_kwh + dfh.secondary_kwh

    # Store annual and monthly totals.
    # Annual totals is a Pandas Series.
    total_cols = [
        "hp_load_mmbtu",
        "secondary_load_mmbtu",
        "hp_kwh",
        "secondary_fuel_mmbtu",
        "secondary_kwh",
        "space_heat_kwh",
    ]
    dfm = dfh.groupby("month")[total_cols].sum()

    # Add a column for the fraction of the total heat load served by the heat pump.
    dfm["hp_load_frac"] = dfm.hp_load_mmbtu / (
        dfm.hp_load_mmbtu + dfm.secondary_load_mmbtu
    )

    # Add a column for the fraction of heat pump capacity used, maximum across hours
    dfm["hp_capacity_used_max"] = dfh.groupby("month")[["hp_capacity_used"]].max()

    # Add in columns for the peak electrical demand during the month
    dfm["hp_kw_max"] = dfh.groupby("month")[["hp_kwh"]].max()
    dfm["secondary_kw_max"] = dfh.groupby("month")[["secondary_kwh"]].max()
    dfm["space_heat_kw_max"] = dfh.groupby("month")[
        ["space_heat_kwh"]
    ].max()  # can't add the above cuz of coincidence

    # physical units for secondary fuel
    fuel = exist_heat_fuel  # shortcut variable
    dfm["secondary_fuel_units"] = dfm["secondary_fuel_mmbtu"] * 1e6 / fuel.btus

    # COP by month
    dfm["cop"] = dfm.hp_load_mmbtu / (dfm.hp_kwh * 0.003412)

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


def determine_ua_true_up(
    heat_model_inputs: HeatModelInputs, secondary_fuel_use_actual: float
) -> float:
    """Returns a UA true up multiplier that causes the space heat model to match the actual space
    heating use of the home, which is passed in the 'secondary_fuel_use_actual' variable.
    """
    # make a copy of the inputs to work with
    inp = heat_model_inputs.model_copy()

    # set a flag indicating if this uses electric resistance as the existing space heat source
    is_electric = inp.exist_heat_system.heat_fuel_id == ELECTRIC_ID

    # remove heat pump and set UA true to 1.0
    inp.heat_pump = None
    inp.ua_true_up = 1.0

    # model space heat use of the building
    res = model_space_heat(inp)
    # retrieve space heating fuel use expressed in fuel units (e.g. gallon)
    if is_electric:
        fuel_use1 = res.annual_results.secondary_kwh
    else:
        fuel_use1 = res.annual_results.secondary_fuel_units

    # scale the UA linearly to attempt to match the target fuel use
    ua_true_up = secondary_fuel_use_actual / fuel_use1
    inp.ua_true_up = ua_true_up
    res = model_space_heat(inp)

    if is_electric:
        # For electric heat, electric use for space heat is in secondary_kwh
        fuel_use2 = res.annual_results.secondary_kwh
    else:
        fuel_use2 = res.annual_results.secondary_fuel_units

    # In case it wasn't linear, inter/extrapolate to the final ua_true_up
    if ua_true_up != 1.0:
        slope = (fuel_use2 - fuel_use1) / (ua_true_up - 1.0)
        ua_true_up = 1.0 + (secondary_fuel_use_actual - fuel_use1) / slope

    return ua_true_up


def monthly_to_annual_results(df_monthly: pd.DataFrame) -> pd.Series:
    """Aggregrates a monthly model results DataFrame (with columns that are all
    or a subset of TimePeriodResults) into an Annual Pandas series.
    """
    # Get a list of numeric columms by removing the 'period' column.
    numeric_cols = list(df_monthly.columns)
    numeric_cols.remove("period")

    # the most common aggregation is summing so do that to all the columns and
    # then fix the ones that shouldn't be summed.
    annual = df_monthly[numeric_cols].sum()

    # loop through the columns, fixing as needed
    for col in numeric_cols:
        if col in (
            "hp_kw_max",
            "secondary_kw_max",
            "space_heat_kw_max",
            "all_kw_max",
            "hp_capacity_used_max",
        ):
            annual[col] = df_monthly[col].max()

        elif col == "hp_load_frac":
            annual["hp_load_frac"] = annual.hp_load_mmbtu / (
                annual.hp_load_mmbtu + annual.secondary_load_mmbtu
            )

    # the 'cop' column may not be included in the numeric_cols list due to NaN, but it should be inlcuded
    if annual.hp_kwh > 0.0:
        annual["cop"] = annual.hp_load_mmbtu / (annual.hp_kwh * 0.003412)
    else:
        annual["cop"] = np.nan

    # add the period column back in
    annual["period"] = "Annual"

    return annual
