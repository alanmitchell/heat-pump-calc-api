"""Models associated with the home energy and heat pump calculations.
"""
from typing import List
from enum import Enum

from pydantic import BaseModel

# ----------- Enums

class HSPFtype(str, Enum):
    """Type of HSPF rating"""
    hspf2_reg5 = 'hspf2_reg5'    # HSPF2, Climate Region 5
    hspf2_reg4 = 'hspf2_reg4'    # HSPF2, Climate Region 4
    hspf = 'hspf'                # Original HSPF

class BuildingType(str, Enum):
    """Type of Building. Only relevant for determine the amount
    of PCE assistance that the building is eligible for."""
    residential = 'residential'
    commercial = 'commercial'
    community = 'community'

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
    serves_dhw: bool = True               # True if this fuel type heats Domestic Hot Water as well
    serves_clothes_drying: bool = False   # True if this fuel type is used for clothes drying
    serves_cooking: bool = False          # True if this fuel type is used for cooking
    occupant_count: int | None = None     # Number of occupants for purposes of estimating non-space-heat
                                          #     end uses consumption.


class HeatModelInputs(BaseModel):
    """Inputs to the Home Space Heating model."""
    city_id: int                          # ID of City being modeled (use Library cities() method for IDs)
    heat_pump: HeatPump | None = None     # Description of Heat Pump. If None, then no heat pump.
    exist_heat_system: ConventionalHeatingSystem   # Description of existing, non-heat-pump heating system
    building_type: BuildingType = BuildingType.residential  # Type of building, relevant for PCE 
                                                            #    applicability and limits.
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
    monthly_results: List[HeatTimePeriodResults]   # monthly totals of key modeling results
    annual_results: HeatTimePeriodResults   # Annual totals of key modeling results
    design_heat_temp: float                 # 99% design heating temperature, deg F
    design_heat_load: float                 # 99% design heating load, BTU/hour

# ---------------------------------------------

# Models related to Heat Pump analysis.

class HeatPumpCost(BaseModel):
    """Cost information about installing, operating, and potentially financing
    a heat pump.
    """
    capital_cost: float                # Installation cost, $
    rebate_amount: float = 0.0         # Rebate $ available to offset installation cost
    heat_pump_life: int = 14           # Life of heat pump in years
    op_cost_chg: float = 0.0           # Change in annual heating system operating cost due to use of 
                                       #    heat pump. A positive value means increase in operating cost.
    frac_financed: float = 0.0         # Fraction of the (capital_cost - rebate_amount) that is financed, 0 - 1.0
    loan_term: int | None = None       # Length of loan in years
    loan_interest: float | None = None # Loan interest rate, expressed as fraction, e.g. 0.055 for 5.5%

class EconomicInputs(BaseModel):
    """ Inputs related to fuel and electricity costs and economic analysis factors.
    """
    utility_id: int                          # ID of the electric utility rate schedule serving the building
    include_pce: bool = True                 # If True, PCE assistance will be included for this building
    pce_limit: float = 750.0                 # kWh limit per month for PCE assistance
    elec_rate_forecast_pattern: List[float] = [1.0]   # A list of electric price multipliers for the years
                                                      #    spanning the life the of the heat pump. If the list is
                                                      #    shorter than the life, the last value is extended for 
                                                      #    missing years.
    elec_rate_override: float | None = None         # If provided, overrides the electric energy and demand 
                                                    #    charges in the Utility rate schedule
    pce_rate_override: float | None = None          # Overrides the PCE rate in the Utility rate schedule
    customer_charge_override: float | None = None   # Overrides Utility customer charge
    co2_lbs_per_kwh_override: float | None = None   # Overrides Utility CO2 pounds per kWh of Utility electricity
    fuel_cost_override: float | None = None         # Overrides the fuel cost for the city.
    fuel_cost_forecast_pattern: List[float] = [1.0] # A list of fuel price multipliers for years spanning heat pump life
                                                    #    If shorter than heat pump life, last value is extended.
    sales_tax_override: float | None = None         # Overrides sales tax (city + borough) for the city
    discount_rate: float = 0.03                     # Economic discount rate as a fraction for Present Value
                                                    #    calculations, inflation-adjusted, 0.03 for 3% / year
    inflation_rate: float = 0.023                   # General inflation rate, expressed as a fraction, 0.02 for 2% / year

class ActualFuelUse(BaseModel):
    """This model describes the actual fuel and electricity use of the building assuming
    *no* heat pump, so the electricity use is actual use prior to installing a heat pump.
    """
    secondary_fuel_units: float | None = None  # This is the annual amount of fuel used by the building, the fuel being
                                               #    the type used for space heating.  Express this value in the normal 
                                               #    units used for the fuel, e.g. gallons for oil.
    electric_use_by_month: List[float | None] | None = None   # A 12-element list of the monthly electricity use of the building in kWh
                                                #   unkown values can be set to None.

class HeatPumpAnalysisInputs(BaseModel):
    """Describes all the inputs used the analysis of the heat pump
    """
    bldg_name: str = ''                  # Building Name
    notes: str = ''                      # Notes about the analysis
    bldg_model_inputs: HeatModelInputs   # Inputs describing the space heating characteristics of the building
    heat_pump_cost: HeatPumpCost         # Inputs describing the cost of installing and operating the heat pump
    economic_inputs: EconomicInputs      # Fuel and Electricity price inputs and general economic inputs.
    actual_fuel_use: ActualFuelUse       # Information about the actual fuel and electricity use of the home
                                         #    prior to installing the heat pump.

class HeatPumpAnalysisResults(BaseModel):
    """Results from the analysis of installing a heat pump.
    """
    val1: float = -99.0