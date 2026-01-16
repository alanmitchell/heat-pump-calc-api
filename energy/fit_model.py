"""
Adjusts certain building characteristics to best match acutal fuel use to 
modeled fuel use.
"""
from copy import deepcopy
import math
import functools
import json

import numpy as np
from scipy.optimize import minimize

from .models import EnergyModelFitInputs, EnergyModelFitOutput
from .models import Fuel_id
from .energy_model import model_building

from library.library import fuel_from_id
from general.dict2d import Dict2d


def fit_model(inp: EnergyModelFitInputs) -> EnergyModelFitOutput:
    """Tunes key properties of a Building Description to best fit actual fuel
    use data.  Returns the new Building Description with the key properties set
    at the best-fit values and returns error fractions.
    
    The properties of the Building Description that are manipulated are:

        ua_per_ft2
        The 'frac_load_served' property of the Primary and Secondary Conventional Heating Systems
        misc_elec_kwh_per_day
        misc_elec_seasonality
        EV charging miles / kWh
        EV charging seasonality
        Home PV Solar annual production per kW installed.
    """
    # call a function with a JSON input so that the function can be cached.
    # A Pydantic object is not hashable so can't be lru cached.
    inp_dict = inp.model_dump(mode='json')
    inp_cacheable = json.dumps(inp_dict, sort_keys=True, separators=(",", ":"))
    return fit_model_json_input(inp_cacheable)

@functools.lru_cache(maxsize=100)
def fit_model_json_input(inp_json):

    # Build a Pydantic object from the JSON to use in the ModelFitter class.
    # (dot access to propertiess is nice.)
    inp = EnergyModelFitInputs.model_validate_json(inp_json)
    model_fitter = ModelFitter(inp)
    return model_fitter.fit()


class ModelFitter:

    def __init__(self, inp:EnergyModelFitInputs):

        # Save the key inputs, processed a bit, so they can be accessed by the class methods.

        # make a copy of the building description so that properties can be manipulated without
        # affecting the original.
        self.bldg = deepcopy(inp.building_description)    # a copy to work with

        # Convert actual fuel use to MMBTU so that there is common unit for calculating total error.
        self.actual_fuel = {}
        for fuel_id, use in inp.actual_fuel_by_type.items():
            fuel_info = fuel_from_id(fuel_id)
            self.actual_fuel[fuel_id] = use * fuel_info.btus / 1e6
        # make accessible the original use expressed in fuel units
        self.actual_fuel_units = inp.actual_fuel_by_type

        # convert actual electric use to MMBTU and then store as Numpy array
        self.elec_actual = np.array(inp.electric_use_by_month) * 0.003412
        # also retain original.
        self.elec_actual_kwh = np.array(inp.electric_use_by_month)

    def fit(self):
        """Determine the best-fitting property values of the building description to
        minimize the error with actual use. Return the resulting building description object.
        """
        # determine initial values for the building properties being varied
        init_params = [
            0.19,            # UA per ft2
            1.0 if self.bldg.conventional_heat[1].heat_fuel_id is None else 0.75,    # primary heat load frac
            5.72 + 0.00329 * self.bldg.bldg_floor_area,     # misc electric kWh/day, AkWarm - 25%
            0.15,             # seasonal variation for misc electric
            3.0,              # ev miles / kWh
            0.0,              # ev seasonal variation
            650.0,            # solar kWh-annual / kW installed
        ]

        # determine bounds on parameters
        bounds = [
            (0.096, 0.52),    # roughly the 2.5% - 97.5% range according to AkWarm dataset
            (1.0, 1.0) if self.bldg.conventional_heat[1].heat_fuel_id is None else (0.4, 1.0),   
            (init_params[2] / 2.0 , init_params[2] * 2.0),  # 1/2 to double estimated average
            (-0.1, 0.30),      # Could be reverse seasonality of snow bird.
            (1.8, 3.5) if self.bldg.ev_charging_miles_per_day else (3.0, 3.0),     # EV miles / kWh
            (-0.15, 0.15) if self.bldg.ev_charging_miles_per_day else (0.0, 0.0),  # EV seasonality
            (450.0, 950.0) if self.bldg.solar_kw else (650.0, 650.0) ,    # Solar kWh / kW
        ]

        self.n = 0
        
        result = minimize(
            self.model_error,
            init_params,
            method="L-BFGS-B",
            bounds=bounds,
            options={
                "maxiter": 50,
                "ftol": 1e-4
            }
        )
        #print(result.success, result.fun, result.nit, self.n)

        # Fill out building description with best-fit properties
        self.bldg.ua_per_ft2 = result.x[0]
        self.bldg.conventional_heat[0].frac_load_served = result.x[1]
        self.bldg.conventional_heat[1].frac_load_served = 1.0 - result.x[1]
        self.bldg.misc_elec_kwh_per_day = result.x[2]
        self.bldg.misc_elec_seasonality = result.x[3]
        self.bldg.ev_miles_per_kwh = result.x[4]
        self.bldg.ev_seasonality = result.x[5]
        self.bldg.solar_kwh_per_kw = result.x[6]

        # run the best fit description through the energy model.
        results = model_building(self.bldg)

        # Summarize actual, modeled and error for fuels that are used. Use actual
        # fuel units, not MMBTU.
        fuel_fit_info = {}    # each value will be a 3-tuple: (actual, modeled, error)

        # first get modeled fuel measured in fuel units
        fuel_modeled = Dict2d(results.annual_results.fuel_use_units).sum_key1()

        # find fuel IDs for any used fuel, looking at both actual and modeled.
        used_fuels = set([fuel_id for fuel_id, use in fuel_modeled.items() if use > 0.0])
        used_fuels |= set([fuel_id for fuel_id, use in self.actual_fuel_units.items() if use > 0.0])
        for fuel_id in used_fuels:
            actual = self.actual_fuel_units.get(fuel_id, 0.0)
            modeled = fuel_modeled.get(fuel_id, 0.0)
            if actual != 0.0:
                error = (modeled - actual) / actual
            else:
                # JSON didn't like math.inf. Use 0.999 instead
                error = math.copysign(0.999, modeled)
            fuel_fit_info[fuel_id] = (actual, modeled, error)

        # now need to add annual electricity use.
        elec_actual_annual = self.elec_actual_kwh.sum()
        elec_modeled = fuel_modeled.get(Fuel_id.elec, 0.0)
        if elec_actual_annual != 0.0:
            elec_error = (elec_modeled - elec_actual_annual) / elec_actual_annual
        else:
            elec_error = math.copysign(0.999, elec_modeled)
        fuel_fit_info[Fuel_id.elec] = (elec_actual_annual, elec_modeled, elec_error)

        return EnergyModelFitOutput(
            building_description=self.bldg, 
            fuel_fit_info=fuel_fit_info,
            model_results=results
            )

    def model_error(self, params):
        # unpack the input parameters and assign to the building description
        self.n += 1
        ua_per_ft2, primary_load_frac, misc_elec, misc_seasonality, ev_effic, ev_seasonality, solar = params

        self.bldg.ua_per_ft2 = ua_per_ft2
        self.bldg.conventional_heat[0].frac_load_served = primary_load_frac
        self.bldg.conventional_heat[1].frac_load_served = (1.0 - primary_load_frac)
        self.bldg.misc_elec_kwh_per_day = misc_elec
        self.bldg.misc_elec_seasonality = misc_seasonality
        self.bldg.ev_miles_per_kwh = ev_effic
        self.bldg.ev_seasonality = ev_seasonality
        self.bldg.solar_kwh_per_kw = solar

        # run the model
        results = model_building(self.bldg)

        # calculate the total error in estimated fuel use vs. actual.  Error is total
        # of squared error for each fuel use item.
        error_total = 0.0 

        # gather monthly modeled electric use in MMBTU and compute sum of squared error.
        # Note, due to squaring of the error, these monthly error amounts need to be multiplied
        # by 12 to get the magnitude equivalent to squaring annual errors for the other fuels.
        # Otherwise, the minimizer stops too early and leaves large model errors in the electrical
        # use.
        elec_modeled = [Dict2d(r.fuel_use_mmbtu).sum_key1()[Fuel_id.elec] for r in results.monthly_results]
        error_total += ((np.array(elec_modeled) - self.elec_actual)**2).sum() * 12.0

        # add in error from the other fuel uses, measured at the annual level.
        fuel_modeled = Dict2d(results.annual_results.fuel_use_mmbtu).sum_key1()
        for fuel_id, use in self.actual_fuel.items():
            error_total += (use - fuel_modeled.get(fuel_id, 0.0))**2

        return error_total
