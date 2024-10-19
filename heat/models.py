"""Models associated with the home energy and heat pump calculations.
"""
from typing import Tuple, List, Any
from enum import Enum

from pydantic import BaseModel

# ----------- Enums

class HSPFtype(str, Enum):
    """Type of HSPF rating"""
    hspf2_reg5 = 'hspf2_reg5'    # HSPF2, Climate Region 5
    hspf2_reg4 = 'hspf2_reg4'    # HSPF2, Climate Region 4
    hspf = 'hspf'                # Original HSPF

class WallInsulLevel(str, Enum):
    """Description of Wall Insulation"""
    wall2x4 = 'wall2x4'          # 2x4 fiberglass wall
    wall2x6 = 'wall2x6'          # 2x6 fiberglass wall
    wall2x6plus = 'wall2x6plus'  # Insulated better than 2x6 fiberglass

class TemperatureTolerance(str, Enum):
    """Describes amount of indoor temperature drop that is considered acceptable."""
    low = 'low'          # only a small drop is acceptable
    med = 'med'          # 5 deg F drop is acceptable
    high = 'high'        # 10 deg F drop is acceptable

# --------------- Pydantic Models for Space Heating Models

class HeatPump(BaseModel):
    """Description of a Heat Pump and Operation Strategy"""
    hspf_type: HSPFtype = HSPFtype.hspf2_reg5     # Type of HSPF specified below
    hspf: float                       # HSPF value of the type determined by hspf_type
    max_out_5f: float                 # maximum heat output at 5 degree F, BTU / hour
    low_temp_cutoff: float = 5.0      # Temperature deg F below which heat pump is not operated. Evaluated on daily basis, 20% of hours must be below.
    off_months: List[int] | None = None       # Tuple of Month Numbers (1 = January) for months where heat pump is shut off entirely.
    frac_exposed_to_hp: float              # fraction of the home that is open to the Heat Pump Indoor units (no doorway separating)
    frac_adjacent_to_hp: float             # fraction of the home that is adjacent to the space where the Heat Pump Indoor units are located (one doorway away)
    doors_open_to_adjacent: bool          # True if doors are open to rooms adjoining those containing Heat Pump Indoor Units.
    bedroom_temp_tolerance: TemperatureTolerance      # 'low' - little temp drop allowed in back rooms,  'med' - 5 deg F cooler is OK, 'high' - 10 deg F cooler is OK
    serves_garage: bool = False            # True if garage is heated by heat pump.

class ConventionalHeatingSystem(BaseModel):
    """Describes a non-heat-pump heating system"""
    heat_fuel_id: int   # ID of heating system fuel type (use Library fuels() method for IDs)
    heating_effic: float    # 0 - 1.0 seasonal heating efficiency
    aux_elec_use: float     # Auxiliary fan/pump/controls electric use, expressed as kWh/(MMBTU heat delivered)

class HeatModelInputs(BaseModel):
    """Inputs to the Home Space Heating model."""
    city_id: int                          # ID of City being modeled (use Library cities() method for IDs)
    heat_pump: HeatPump | None = None     # Description of Heat Pump. If None, then no heat pump.
    exist_heat_system: ConventionalHeatingSystem   # Description of existing, non-heat-pump heating system
    garage_stall_count: int               # 0: No garage, 1: 1-car garage.  Max is 4.
    bldg_floor_area: float                # Floor area in square feet of home living area, not counting garage.
    indoor_heat_setpoint: float = 70.0    # Indoor heating setpoint, deg F
    insul_level: WallInsulLevel = WallInsulLevel.wall2x6    # 1: 2x4, 2: 2x6, 3: better than 2x6 Walls

    # The inputs below are not user inputs, they control the 
    # calculation process. They are given default values.
    ua_true_up: float = 1.0          # used to true up calculation to actual fuel use. Multiplies the UA determined from insulation level.

class HeatTimePeriodResults(BaseModel):
    period: str                # time period being reported on, e.g. "Jan" for January, "Annual" for full year
    hp_load_mmbtu: float       # heat load in MMBTU served by heat pump
    hp_kwh: float              # kWh consumed by heat pump
    hp_kw_max: float           # max kW demand of heat pump
    hp_capacity_used_max: float   # Fraction of the heat pump capacity used, maximum, 0 - 1.0
    cop: float | None             # average heat pump COP for the period
    secondary_load_mmbtu: float   # heat load in MMBTU served by secondary, conventional, heating system
    secondary_fuel_mmbtu: float   # fuel consumed by the secondary system in MMBTU
    secondary_fuel_units: float   # fuel consumed by the secondary system in units of fuel, e,g, 'gallon'
    secondary_kwh: float          # electricity consumed by secondary system, usually for auxiliaries, but also includes electric heat kWh
    secondary_kw_max: float       # max electricity used by secondary system in kW
    total_kwh: float              # total electricity kWh used by heat pump and secondary system
    total_kw_max: float           # maximum kW coincident demand by heat pump and secondary heating system


class HeatModelResults(BaseModel):
    """Space Heat Model results"""
    monthly_results: List[HeatTimePeriodResults]
    annual_results: HeatTimePeriodResults


