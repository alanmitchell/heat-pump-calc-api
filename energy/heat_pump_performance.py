"""Creates COP and maximum output capacity versus outdoor air temperature for a Heat Pump.
"""
from typing import Tuple

import numpy as np

from .models import HSPFtype, HeatPumpSource
from .hspf_convert import convert_to_hspf

# ------------- Air-source COP vs. outdoor temperature based on field studies.
# Piecewise linear COP vs. outdoor air temperature.  See the notebook at
# https://github.com/alanmitchell/heat-pump-study/blob/master/general/cop_vs_temp.ipynb
# for derivation of the original values of this curve.  It was based on averaging a number
# of field studies of heat pump performance. The values below contain two modifications of that
# original curve:
#     1. COPs were reduced by a factor of 0.9 on March 2022 to bring them into better
#        alignment with measured Seward COPs of 2.66 for HSPF = 15.0 Gree unit, and
#        COP = 2.62 for HSPF = 13.3 Fujitsu unit (both units owned by Phil Kaluza).
#     2. The original COP curve dropped off rapidly at low outdoor temperatures.
#        Cold chamber testing of popular Alaskan mini-splits by Tom Marsik at CCHRC
#        showed a much less rapid drop off of COP at cold temperatures. The curve below
#        uses Tom's drop-off slope for temperatures less than 2 deg F.
#        see '/home/alan/gdrive/Heat_pump/models/low-temp-cop.ipynb for the details of
#        the new low-temperature figures.

COP_vs_TEMP = (
    (-20.0, 1.06),
    (-14.0, 1.21),
    (-10.0, 1.30),
    (-6.2, 1.39),
    (-1.9, 1.49),
    (2.0, 1.58),
    (6.0, 1.70),
    (10.8, 1.84),
    (14.2, 1.93),
    (18.1, 2.03),
    (22.0, 2.13),
    (25.7, 2.21),
    (29.9, 2.25),
    (34.5, 2.44),
    (38.1, 2.59),
    (41.8, 2.70),
    (46.0, 2.79),
    (50.0, 2.91),
    (54.0, 2.99),
    (58.0, 3.09),
    (61.0, 3.16),
)

# convert to separate lists of temperatures and COPs
TEMPS_FIT, COPS_FIT = tuple(zip(*COP_vs_TEMP))
TEMPS_FIT = np.array(TEMPS_FIT)
COPS_FIT = np.array(COPS_FIT)

# The HSPF value (old HSPF, not HSPF2) that this curve is associated with.  This is the 
# average of the HSPFs for the studies used to create the above COP vs. Temperature curve.
# See the above referenced Jupyter notebook for more details.
BASE_HSPF = 11.33

# ------------ Ground Source Constants

# Amount of temperature difference between the Ground Temperature and the Entering 
# Water Temperature of a Ground/Water Source Heat Pump
GROUND_EWT_DELTA_T = 6.0       # degrees F

# Used to adjust COP @ 32 F EWT to a value at a different EWT
# See https://docs.google.com/spreadsheets/d/1Hq_NqUUOZLOgLyldf-Fz-T5h0-F6Ht-9QBE1Dn1WCCQ/
EWT_COP_ADJ = 0.0113          # see how this constant is used in code later in the module

# ---------------------------------

def air_source_performance(
        hspf_rating: float | None, 
        hspf_type: HSPFtype | None,
        cop_at_32f: float | None,
        max_capacity_at_5f: float,
        indoor_heat_setpoint: float
        ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns matched outdoor temperature, heat pump COP, and 
    max output capacity arrays.
    """
    # Create an adjusted COP curve that accounts for the actual HSPF (or COP) of
    # this heat pump.  

    if hspf_rating:
        # Adjust the field study curve by ratioing the actual HSPF of this unit
        # to the average HSPF of the units in the field studies.
        # Because of the weak correlation of HSPF to actual performance,
        # the HSPF adjustment here is not linear, but instead dampened by raising
        # the ratio to the 0.5 power.  This was a judgement call.

        # Convert other HSPF values into old HSPF
        hspf_old = convert_to_hspf(hspf_rating, hspf_type)

        cop_adj_mult = (hspf_old / BASE_HSPF) ** 0.5

    else:
        # No HSPF so there must be a COP at 32 F provided. Trust it as accurate, and
        # adjust the field study COP curve to match it.
        cop32_from_study = np.interp(32.0, TEMPS_FIT, COPS_FIT)
        cop_adj_mult = cop_at_32f / cop32_from_study

    cops_adj = COPS_FIT * cop_adj_mult

    # Also adjust the associated outdoor air temperature points to account for the fact
    # that the indoor temperature setpoint does not equal the 70 degree F
    # temperature average from the field studies that developed the COP curve.
    temps_fit_adj = TEMPS_FIT + (indoor_heat_setpoint - 70.0)

    # determine max capacity across the temperature points assuming it scales with COP.
    # The max capacity value assumes an indoor temperature of 70 F, so scale from the
    # unadjusted temperature array.
    cop5F_70F = np.interp(5.0, TEMPS_FIT, cops_adj)

    # Now make a multiplier array that ratios off this COP
    capacity_mult = cops_adj / cop5F_70F

    # Make an array that is the max output at each of the adjusted temperature
    # points.
    max_capacity_array = capacity_mult * max_capacity_at_5f

    return temps_fit_adj, cops_adj, max_capacity_array

def ground_source_performance(
        cop_at_32f: float, 
        max_capacity_at_32f: float,
        indoor_heat_setpoint: float, 
        ground_temperature: float
        ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """This is a simplistic algorithm and could use improvement.
    Assume that the cop_32 value is the actual COP at 32 F source temp, not just a rated
    value. Also assume the cop_32 value assumes 70 F indoor temperature. Assume the COP does 
    not change with outdoor air temperature; determine 
    this constant COP value from the ground temperature. Assume the maximum output capacity is also
    constant across outdoor air temperatures but scales with the COP.
    """

    # estimate the EWT temperature from ground temperature
    ewt_temp = ground_temperature - GROUND_EWT_DELTA_T

    # Adjust the 32 F COP based on this ewt temp and any deviation from a 70 F
    # indoor setpoint
    cop = cop_at_32f * (1.0 + EWT_COP_ADJ * (ewt_temp - 32.0 + 70.0 - indoor_heat_setpoint))

    # Adjust the max capacity based on  this adjusted COP
    max_capacity = max_capacity_at_32f * cop / cop_at_32f

    # make a COP array matching the temperature array with this same value for all elements.
    cop_array = np.array([cop] * len(TEMPS_FIT))

    # make a maximum capacity matching the temperature array with the same value for all
    # elements.
    max_capacity_array = np.array([max_capacity] * len(TEMPS_FIT))

    return TEMPS_FIT, cop_array, max_capacity_array
