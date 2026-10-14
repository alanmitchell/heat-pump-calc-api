"""
Script for running test cases of COP and max capacity for various heat
pump configurations.  Run in the root project directory with:

    uv run test-cop-capacity.py
"""
from typing import Tuple

import numpy as np

from energy.heat_pump_performance import air_source_performance, ground_source_performance
from energy.models import HSPFtype

air_tests = (
    (13.5, HSPFtype.hspf, None, 11300, -3.5, 70.0),
    (13.5, HSPFtype.hspf, None, 11300, 18.3, 73.0),
    (12.2, HSPFtype.hspf2_reg4, None, 9200, 15.2, 68.5),
    (12.2, HSPFtype.hspf2_reg4, None, 9200, 42.3, 71.0),
    (10.2, HSPFtype.hspf2_reg5, None, 14200, 7.3, 69.0),
    (10.2, HSPFtype.hspf2_reg5, None, 14200, 28.4, 71.5),
    (None, None, 2.56, 12100, 14.8, 70.5),
    (None, None, 2.56, 12100, 36.2, 68.2),
    )

ground_tests = (
    (2.8, 32000, 36.0, -3.2, 70.0),
    (2.8, 32000, 29.0, 18.0, 71.5),
    (2.3, 26500, 33.3, 14.3, 72.0),
    (2.3, 26500, 34.7, 43.0, 69.0),

)

def cop_and_max_capacity(
        out_temp: float, 
        out_temp_arr: np.ndarray,
        cop_arr: np.ndarray,
        max_capacity_arr: np.ndarray) -> Tuple[float, float]:

    """Returns COP and maximum capacity at outdoor temperature or 'out_temp'.
    """
    cop = np.interp([out_temp,], out_temp_arr, cop_arr)
    max_capacity = np.interp([out_temp,], out_temp_arr, max_capacity_arr)
    
    return cop, max_capacity

# Air Source Tests
print('Air Source Results')
for hspf, hspf_type, cop_32, max_capacity_5, out_temp, indoor_setpt in air_tests:

    out_temp_arr, cop_arr, max_capacity_arr = air_source_performance(
        hspf, hspf_type, cop_32, max_capacity_5,indoor_setpt)
    cops, capacities = cop_and_max_capacity(out_temp, out_temp_arr, cop_arr, max_capacity_arr)
    print(cops[0], capacities[0])

# Ground Source Tests
print()
print('Ground Source Results')
for cop_32, max_capacity_32, gnd_temp, out_temp, indoor_setpt in ground_tests:

    out_temp_arr, cop_arr, max_capacity_arr = ground_source_performance(
        cop_32, max_capacity_32,indoor_setpt, gnd_temp)
    cops, capacities = cop_and_max_capacity(out_temp, out_temp_arr, cop_arr, max_capacity_arr)
    print(cops[0], capacities[0])

