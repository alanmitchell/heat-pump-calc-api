"""Used to convert newer HSPF2 values into old HSP values.

The work supporting these conversions is at
/home/alan/gdrive/Heat_Pump/neep-data/neep-for-hp-calculator.ipynb.
That notebook analyzed an October 2023 NEEP Heat Pump database, which
contained thousands of heat pump units with HSPF and HSPF2 ratings.
"""

import numpy as np

from .models import HSPFtype

# piecewise linear curves to do to conversion
# The first four points for each conversion come from the above
# referenced notebook. The last point (highest HSPF) is extrapolated
# using the slope from developed from the 2nd and 4th points

# To convert from HSPF2 Region 4
from_hspf2reg4_x = np.array([7.75, 8.25, 12.5, 14.0, 16.0])
from_hspf2reg4_y = np.array([9.36, 9.55, 13.1, 14.5, 14.5 + 0.861 * 2.0])

# To convert from HSPF2 Region 5
from_hspf2reg5_x = np.array([6.25, 7.25, 10.5, 11.25, 15.0])
from_hspf2reg5_y = np.array([9.62, 10.1, 13.2, 13.6, 13.6 + 0.875 * 3.75])

# Note that np.interp extends the endpoint y values for x values that are
# outside the range of x-values in array.


def convert_to_hspf(hspf_value: float, hspf_type: HSPFtype) -> float:
    """Converts an HSPF value of type indicated by 'hspf_type' into the
    an old-version HSPF (Region IV) value"""

    if hspf_type == HSPFtype.hspf:
        # it is already the old-version HSPF
        return hspf_value

    elif hspf_type == HSPFtype.hspf2_reg4:
        return np.interp(hspf_value, from_hspf2reg4_x, from_hspf2reg4_y)

    elif hspf_type == HSPFtype.hspf2_reg5:
        return np.interp(hspf_value, from_hspf2reg5_x, from_hspf2reg5_y)
