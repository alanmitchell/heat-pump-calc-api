"""The main function "analyze_heat_pump" determines the impact and economics of
installing a heat pump in a building. This module uses the space heating model
(model_space_heat()) found in the "home_heat_model" module.
"""
from pprint import pformat
import inspect
from pathlib import Path
import pickle
import time
import gzip

import pandas as pd
import numpy as np
import numpy_financial as npf

from .models import HeatPumpAnalysisInputs, HeatPumpAnalysisResults
from .home_heat_model import model_space_heat, ELECTRIC_ID, determine_ua_true_up
from .elec_cost import ElecCostCalc
import library.library as lib
from general.utils import is_null, chg_nonnum

# --------- Some Constants

# The days in each month
DAYS_IN_MONTH = np.array([
    31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31
])

# The pattern of Lights and appliances other than DHW, Clothes Drying & Cooking.
# This is average power in the month divided average annual power.
LIGHTS_OTHER_PAT = np.array([
    1.13, 1.075, 1.0, 0.925, 0.87, 0.85, 0.87, 0.925, 1.0, 1.075, 1.13, 1.15
])

def make_pattern(esc, life):
    """Makes a numpy array of length (life + 1) containing an escalation pattern
    that starts with a 1.0 in year 1 and escalates at the rate of 'esc' per year.
    """
    pat = np.ones(life - 1) * (1 + esc)
    return np.insert(pat.cumprod(), 0, [0.0, 1.0])

def convert_co2_to_miles_driven(co2_saved: float) -> float:
    """Converts CO2 emissions to a mileage driven
    equivalent for vehicles in the U.S. using EPA
    methodology:  https://www.epa.gov/energy/greenhouse-gases-equivalencies-calculator-calculations-and-references#miles
    """
    pounds_in_metric_ton = 2204.62
    tons_co2_per_gallon = 0.0089
    avg_gas_mileage_us_fleet = 22
    mileage_equivalent = co2_saved / pounds_in_metric_ton / tons_co2_per_gallon * avg_gas_mileage_us_fleet
    
    return mileage_equivalent

def analyze_heat_pump(inp: HeatPumpAnalysisInputs) -> HeatPumpAnalysisResults:
    """Performs a performance and economic analysis of installing a Heat Pump.
    """
    # Start results dictionary
    res = {}

    # shortcuts to some of the input structures
    inp_bldg = inp.bldg_model_inputs
    inp_hpc = inp.heat_pump_cost
    inp_econ = inp.economic_inputs
    inp_actual = inp.actual_fuel_use

    # acquire some key objects
    city = lib.city_from_id(inp.bldg_model_inputs.city_id)
    fuel = lib.fuel_from_id(inp.bldg_model_inputs.exist_heat_system.heat_fuel_id)
    elec_util = lib.util_from_id(inp_econ.utility_id)

    # If other end uses use the heating fuel, make an estimate of their annual
    # consumption of that fuel.  This figure is expressed in the physical unit
    # for the fuel type, e.g. gallons of oil.  
    # See Evernote notes on values (AkWarm for DHW and Michael Bluejay for Drying 
    # and Cooking).
    is_electric = (fuel.id == ELECTRIC_ID)  # True if Electric
    fuel_other_uses = inp_bldg.exist_heat_system.serves_dhw * 4.23e6 / fuel.dhw_effic     # per occupant value
    fuel_other_uses += inp_bldg.exist_heat_system.serves_clothes_drying * (0.86e6 if is_electric else 2.15e6)
    fuel_other_uses += inp_bldg.exist_heat_system.serves_cooking * (0.64e6 if is_electric else 0.8e6)
    # assume 3 occupants if no value is provided.
    fuel_other_uses *= chg_nonnum(inp_bldg.exist_heat_system.occupant_count, 3.0) / fuel.btus

    # For elecric heat we also need to account for lights and other applicances not
    # itemized above.
    if is_electric:
        # Use the AkWarm Medium Lights/Appliances formula but take 25% off
        # due to efficiency improvements since then.
        lights_other_elec = 2086. + 1.20 * inp_bldg.bldg_floor_area   # kWh in the year
    else:
        lights_other_elec = 0.0

    # Match the existing space heating use if it is provided.  Do so by using
    # the UA true up factor.
    if inp_actual.secondary_fuel_units is not None:
        
        # Remove the energy use from the other end uses that use the fuel, unless
        # this is electric heat and the user indicated that the entered value is
        # just space heating.
        if is_electric and inp.actual_fuel_use.annual_electric_is_just_space_heat:
            # user explicitly indicated that the entered annual usage value is
            # just space heating.
            space_fuel_use = inp.actual_fuel_use.secondary_fuel_units
        else:
            space_fuel_use = inp.actual_fuel_use.secondary_fuel_units - fuel_other_uses
            if is_electric:
                # if electric heat, also need to subtract out other lights and appliances
                space_fuel_use -= lights_other_elec

        ua_true_up = determine_ua_true_up(inp_bldg, space_fuel_use)

    else:
        ua_true_up = 1.0
        
    # Set the UA true up value into the model and also save it as
    # an attribute of this object so it can be observed.
    inp_bldg.ua_true_up = ua_true_up
    
    res['ua_true_up'] = ua_true_up

    # Run the base case with no heat pump and record energy results.
    # This model only models the space heating end use.
    bldg_no_hp = inp_bldg.model_copy()
    bldg_no_hp.heat_pump = None
    en_base = model_space_heat(bldg_no_hp)

    # Run the model with the heat pump and record energy results
    en_hp = model_space_heat(inp_bldg)

    # record design heat load and temperature
    res['design_heat_load'] = en_hp.design_heat_load
    res['design_heat_temp'] = en_hp.design_heat_temp
    
    # Calculate some summary measures
    res['annual_cop'] = en_hp.annual_results.cop
    res['hp_max_out_5F'] = inp_bldg.heat_pump.max_out_5f
    res['max_hp_reached'] = (en_hp.annual_results.hp_capacity_used_max == 1.0)
    
    # CO2 savings. If secondary fuel is electric, fuel.co2 is None, so protect against that.
    co2_base = en_base.annual_results.total_kwh * elec_util.CO2 + en_base.annual_results.secondary_fuel_mmbtu * chg_nonnum(fuel.co2, 0.0)
    co2_hp = en_hp.annual_results.total_kwh * elec_util.CO2 + en_hp.annual_results.secondary_fuel_mmbtu * chg_nonnum(fuel.co2, 0.0)
    res['co2_lbs_saved'] = co2_base - co2_hp
    res['co2_driving_miles_saved'] = convert_co2_to_miles_driven(res['co2_lbs_saved'])

    res['hp_load_frac'] = en_hp.annual_results.hp_load_mmbtu / (en_hp.annual_results.hp_load_mmbtu + en_hp.annual_results.secondary_load_mmbtu)

    return HeatPumpAnalysisResults(**res)
