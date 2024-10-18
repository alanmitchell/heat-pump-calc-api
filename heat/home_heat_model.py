"""Holds the class 'HomeHeatModel' that simulates the space heating 
energy use of the home either with or without the heat pump.
"""
from typing import Tuple

import numpy as np
import pandas as pd

from . import constants
from .models import (
    HeatModelInputs,
    HeatTimePeriodResults,
    HeatModelResults, 
    WallInsulLevel, 
    TemperatureTolerance,
)
from library import library as lib
from general.utils import chg_nonnum

# Some General Constants
ELECTRIC_ID = 1    # The fuel ID for Electricity

# ------- Data needed for calculation of COP vs. Temperature

# Piecewise linear COP vs. outdoor temperature.  See the notebook at
# https://github.com/alanmitchell/heat-pump-study/blob/master/general/cop_vs_temp.ipynb
# for derivation of this curve.  It is based on averaging a number of field studies
# of heat pump performance.
COP_vs_TEMP = (
    (-20.0, 0.66),
    (-14.0, 1.11),
    (-10.0, 1.41),
    (-6.2, 1.54),
    (-1.9, 1.67),
    (2.0, 1.76),
    (6.0, 1.89),
    (10.8, 2.04),
    (14.2, 2.15),
    (18.1, 2.26),
    (22.0, 2.37),
    (25.7, 2.46),
    (29.9, 2.50),
    (34.5, 2.71),
    (38.1, 2.88),
    (41.8, 3.00),
    (46.0, 3.10),
    (50.0, 3.23),
    (54.0, 3.32),
    (58.0, 3.43),
    (61.0, 3.51),
)

# convert to separate lists of temperatures and COPs
TEMPS_FIT, COPS_FIT = tuple(zip(*COP_vs_TEMP))
TEMPS_FIT = np.array(TEMPS_FIT)
COPS_FIT = np.array(COPS_FIT)

# March 2022 adjustment to COPs.  A downward adjustment was made so that the model comes
# into better alignment with measured Seward COPs of 2.66 for HSPF = 15.0 Gree unit, and 
# COP = 2.62 for HSPF = 13.3 Fujitsu unit (both units owned by Phil Kaluza).
COP_ADJ = 0.9
COPS_FIT = COP_ADJ * COPS_FIT

# The HSPF value that this curve is associated with.  This is the average of the HSPFs
# for the studies used to create the above COP vs. Temperature curve.  See the above 
# referenced Jupyter notebook for more details.
BASE_HSPF = 11.33

# -------------- OTHER CONSTANTS ---------------

GARAGE_HEATING_SETPT = 55.0    # deg F

def temp_depression(ua_per_ft2, 
                    balance_point, 
                    outdoor_temp,
                    doors_open):
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
    temp_depress = temp_delta * r_to_bedroom / (r_to_bedroom + 1.0/ua_per_ft2)
    return temp_depress


def design_heat_load(self) -> Tuple[float, float]:
    """Returns the 99% design heat load for the building and the associated
    design temperature, including the garage if present.  Do not account for 
    any internal or solar gains, as is conventional.
    Return values are Btu/hour and deg F. 
    """
    # get the 1% outdoor temperature
    design_temp = lib.heating_design_temp(self.city.TMYid)
    design_load = self.ua_home * (self.indoor_heat_setpoint - design_temp) + \
                    self.ua_garage * (GARAGE_HEATING_SETPT - design_temp)
    return design_load, design_temp

# ---------------- Main Calculation Method --------------------

def model_space_heat(inp: HeatModelInputs) -> HeatModelResults:
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
    hourly_recs = [rec.dict() for rec in tmy_site.records]
    df_tmy = pd.DataFrame(hourly_recs)
    dfh = df_tmy[['db_temp', 'month']].copy()
    dfh['day_of_year'] = [i for i in range(1, 366) for _ in range(24)]

    if inp.heat_pump is not None:

        # Determine days that the heat pump is running.  Look at the 20th percentile
        # temperature for the day, and ensure that it is above the low 
        # temperature cutoff.
        hp_is_running = lambda x: (x.quantile(0.2) > inp.heat_pump.low_temp_cutoff)
        dfh['running'] = dfh.groupby('day_of_year')['db_temp'].transform(hp_is_running)

        # Also consider whether the user has selected the month as an Off month.
        if inp.heat_pump.off_months is not None:
            off_mask = dfh.month.isin(inp.heat_pump.off_months)
            dfh.loc[off_mask, 'running'] = False

        # Create an adjusted COP curve that accounts for the actual HSPF of 
        # this heat pump. Adjust the COP of this unit by ratioing it to the 
        # average HSPF of the units used to determine the baseline COP vs. Temperature
        # curve.  Because of the weak correlation of HSPF to actual performance,
        # the HSPF adjustment here is not linear, but instead dampened by raising
        # the ratio to the 0.5 power.  This was a judgement call.

        # ** TO DO **: Convert other HSPF values into old HSPF

        cops_fit_adj = COPS_FIT * (inp.heat_pump.hspf / BASE_HSPF) ** 0.5

        # Also adjust the associated outdoor temperature points to account for the fact
        # that the indoor temperature setpoint does not equal the 70 degree F
        # temperature average from the field studies that developed the COP curve.
        temps_fit_adj = TEMPS_FIT + (inp.indoor_heat_setpoint - 70.0)

        # Note that this same COP curve is used if the garage is heated by the heat pump
        # because heatpump condenser temperature will be set by the home indoor setpoint,
        # even though the garage runs at a cooler temperature

        dfh['cop'] = np.interp(dfh.db_temp, temps_fit_adj, cops_fit_adj)

        # Now determine the maximum output of the heat pump at each temperature point. 
        # Do this by trusting the manufacturer's max output at 5 deg F. Use COP ratios
        # to adjust from that value.
        # First get the COP that is associated with the 5 deg F value. This value was 
        # associated with an indoor temperature of 70 deg F, so use the original temperature
        # curve.
        cop5F_70F = np.interp(5.0, TEMPS_FIT, cops_fit_adj)

        # Now make a multiplier array that ratios off this COP
        capacity_mult = cops_fit_adj / cop5F_70F

        # Make an array that is the max output at each of the adjusted temperature
        # points.
        max_hp_output_fit_adj = capacity_mult * inp.heat_pump.max_out_5f

        # Make an hourly array of maximum heat pump output, BTU/hour
        dfh['max_hp_output'] = np.interp(dfh.db_temp, temps_fit_adj, max_hp_output_fit_adj)

    else:
        # No heat pump installed
        dfh['running'] = False
        dfh['cop'] = 1.0       # filler value
        dfh['max_hp_output'] = 0.0

    # adjustment to UA for insulation level.  My estimate, accounting
    # for better insulation *and* air-tightness as you move up the 
    # insulation scale.
    insul_to_ua_adj = {
        WallInsulLevel.wall2x4: 1.25,
        WallInsulLevel.wall2x6: 1.0,
        WallInsulLevel.wall2x6plus: 0.75
    }

    ua_insul_adj = insul_to_ua_adj[inp.insul_level]   # pick the appropriate one
    
    # The UA values below are Btu/hr/deg-F
    # This is the UA / ft2 of the ua_insul_adj = 1.0 home
    # for the main living space.  Assume garage UA is about 10% higher
    # due to higher air leakage.
    # Determined this UA/ft2 below by modeling a typical Enstar home
    # and having the model estimate space heating use of about 1250 CCF.
    # See 'accessible_UA.ipynb'.
    ua_per_ft2 = 0.189
    ua_home = ua_per_ft2 * ua_insul_adj * inp.bldg_floor_area * inp.ua_true_up
    garage_area = (0, 14*22, 22*22, 36*25, 48*28)[inp.garage_stall_count]
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
    max_hp_reached = False       # tracks whether heat pump max output has been reached.

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
        else:
            # Build up the possible heat pump load, and then limit it to 
            # maximum available from the heat pump.

            # Start with all of the load in the spaces exposed to heat pump indoor
            # units.
            hp_ld = home_load * inp.pct_exposed_to_hp

            # Then, garage load if it is heated by the heat pump 
            hp_ld += garage_load * inp.garage_heated_by_hp

            # For the spaces adjacent to the space heated directly by the heat pump,
            # first calculate how much cooler those spaces would be without direct
            # heat.
            temp_depress = temp_depression(
                ua_home / inp.bldg_floor_area,
                balance_point_home,
                h.db_temp,
                inp.doors_open_to_adjacent
            )
            # determine the temp depression tolerance in deg F
            temp_depress_tolerance = {
                TemperatureTolerance.low: 2.0, 
                TemperatureTolerance.med: 5.0, 
                TemperatureTolerance.high: 10.0
                }[inp.bedroom_temp_tolerance]
            # if depression is less than this, include the load
            if temp_depress <= temp_depress_tolerance:
                # I'm not diminishing the load here for smaller delta-T.  It's possible
                # the same diminished delta-T was present in the base case (point-source
                # heating system).  Probably need to refine this.
                hp_ld += home_load * (1.0 - inp.pct_exposed_to_hp)

            # limit the heat pump load to its capacity at this temperature
            hp_ld = min(hp_ld, h.max_hp_output)

            hp_load.append(hp_ld)
            secondary_load.append(total_load - hp_ld)

            if hp_ld >= h.max_hp_output * 0.999:
                # running at within 0.1% of maximum heat pump output.
                max_hp_reached = True

    dfh['hp_load_mmbtu'] = np.array(hp_load) / 1e6
    dfh['secondary_load_mmbtu'] = np.array(secondary_load) / 1e6

    # reduce the secondary load to account for the heat produced by the auxiliary electricity
    # use.
    # convert the auxiliary heat factor for the secondary heating system into an
    # energy ratio of aux electricity energy to heat delivered.
    aux_ratio = inp.exist_heat_system.aux_elec_use * 0.003412
    dfh['secondary_load_mmbtu'] /= (1.0 + aux_ratio)

    # using array operations, calculate kWh use by the heat pump and 
    # the Btu use of secondary system.
    dfh['hp_kwh'] = dfh.hp_load_mmbtu / dfh.cop / 0.003412
    dfh['secondary_fuel_mmbtu'] = dfh.secondary_load_mmbtu / inp.exist_heat_system.heating_effic
    dfh['secondary_kwh'] = dfh.secondary_load_mmbtu * inp.exist_heat_system.aux_elec_use  # auxiliary electric use

    # if this is electric heat as the secondary fuel, move the secondary fuel use into
    # the secondary kWh column and blank out the secondary fuel MMBtu.
    if inp.exist_heat_system.heat_fuel_id  == ELECTRIC_ID:
        dfh.secondary_kwh += dfh.secondary_fuel_mmbtu * 1e6 / exist_heat_fuel.btus
        dfh['secondary_fuel_mmbtu'] = 0.0

    # Make a column for total kWh.  Do this at the hourly level because it is
    # needed to accurately account for coincident peak demand.
    dfh['total_kwh'] = dfh.hp_kwh + dfh.secondary_kwh

    dfh.to_excel('/home/alan/Downloads/dfh.xlsx')

    # res['val1'] = temps_fit_adj
    # res['val2'] = cops_fit_adj
    # res['val3'] = max_hp_output_fit_adj

    # Store annual and monthly totals.
    # Annual totals is a Pandas Series.
    total_cols = ['hp_load_mmbtu', 'secondary_load_mmbtu', 'hp_kwh', 'secondary_fuel_mmbtu', 'secondary_kwh', 'total_kwh']
    dfm = dfh.groupby('month')[total_cols].sum()
    
    # Add in columns for the peak electrical demand during the month
    dfm['hp_kw_max'] = dfh.groupby('month')[['hp_kwh']].max()
    dfm['secondary_kw_max'] = dfh.groupby('month')[['secondary_kwh']].max()
    dfm['total_kw_max'] = dfh.groupby('month')[['total_kwh']].max()  # can't add the above cuz of coincidence

    # physical units for secondary fuel
    fuel = exist_heat_fuel    # shortcut variable
    dfm['secondary_fuel_units'] = dfm['secondary_fuel_mmbtu'] * 1e6 / fuel.btus

    # COP by month
    dfm['cop'] = dfm.hp_load_mmbtu / (dfm.hp_kwh * 0.003412)   

    # Total lbs of CO2 per month, counting electricity and fuel
    dfm['co2_lbs'] = dfm.total_kwh * inp.co2_lbs_per_kwh + dfm.secondary_fuel_mmbtu * chg_nonnum(fuel.co2, 0.0)

    # calculate annual totals. this is a Pandas Series
    tot = dfm.sum()

    # Add in a column to report the period being summarized
    dfm['period'] = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    tot['period'] = 'Annual'

    # Fix the seasonal COP and the peak demand values
    if tot.hp_kwh:
        tot['cop'] =  tot.hp_load_mmbtu * 1e6 / tot.hp_kwh / 3412.
    else:
        tot['cop'] = np.nan
    tot['hp_kw_max'] = dfm['hp_kw_max'].max()    # maximum across all the months
    tot['secondary_kw_max'] = dfm['secondary_kw_max'].max()
    tot['total_kw_max'] = dfm['total_kw_max'].max()

    # Include monthly and annual results
    res['monthly_results'] = [HeatTimePeriodResults(**row) for row in dfm.to_dict(orient='records')]
    res['annual_results'] = tot.to_dict()

    return HeatModelResults(**res)

