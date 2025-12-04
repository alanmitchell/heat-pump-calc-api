"""Models associated with the home energy and heat pump calculations."""

from typing import List, Tuple
from enum import Enum

from pydantic import BaseModel

from econ.models import CashFlowAnalysis

# ----------- Enums


class HSPFtype(str, Enum):
    """Type of HSPF rating"""

    hspf2_reg5 = "hspf2_reg5"  # HSPF2, Climate Region 5
    hspf2_reg4 = "hspf2_reg4"  # HSPF2, Climate Region 4
    hspf = "hspf"  # Original HSPF

class HeatPumpSource(str, Enum):
    """Source of heat for the heaat pump"""

    air = "air"
    ground = "ground"
    water = "water"

class BuildingType(str, Enum):
    """Type of Building. Only relevant for determine the amount
    of PCE assistance that the building is eligible for."""

    residential = "residential"
    commercial = "commercial"
    community = "community"


class WallInsulLevel(str, Enum):
    """Description of Wall Insulation"""

    wall2x4 = "wall2x4"  # 2x4 fiberglass wall
    wall2x6 = "wall2x6"  # 2x6 fiberglass wall
    wall2x6plus = "wall2x6plus"  # Insulated better than 2x6 fiberglass


class TemperatureTolerance(str, Enum):
    """Describes amount of indoor temperature drop that is considered acceptable."""

    low = "low"  # only a small drop is acceptable
    med = "med"  # 5 deg F drop is acceptable
    high = "high"  # 10 deg F drop is acceptable

class Fuel(str, Enum):
    """Fuel types."""

    elec = "elec"
    ng = "ng"
    propane = "propane"
    oil1 = "oil1"
    oil2 = "oil2"
    birch = "birch"
    spruce = "spruce"
    pellets = "pellets"
    coal = "coal"
    steam = "steam"
    hot_water = "hot_water"

class EndUse(str, Enum):
    """Energy End Uses addressed by model"""
    space_htg = "space_htg"    # space heating
    dhw = "dhw"                # domestic hot water
    cooking = "cooking"        # cooking
    drying = "drying"          # drying
    misc_elec = "misc_elec"    # other electric lights and appliances

class EVCharging(str, Enum):
    """Type of Home EV Charging"""
    none = "none"         # None
    level_1 = "level_1"   # Level 1, 120 V
    level_2 = "level_2"   # Level 2, 240 V

# --------------- Pydantic Models for Space Heating Models


class HeatPump(BaseModel):
    """Description of a Heat Pump and Operation Strategy"""

    source_type: HeatPumpSource = HeatPumpSource.air
    hspf_type: HSPFtype | None = HSPFtype.hspf2_reg5  # Type of HSPF specified below
    hspf: float | None = None  # HSPF value of the type determined by hspf_type
    max_out_5f: float | None     # For air-source heat pumps, maximum heat output at 5 degree F, BTU / hour
    cop_32f: float | None = None # COP @ 32 F, realistic value, not rated value.
    max_out_32f: float | None = None   # For ground/water-source heatpumps, maximum heat output at 32 deg F EWT (Entering Water Temperature)
    low_temp_cutoff: float | None = 5.0  # Temperature deg F below which heat pump is not operated. Evaluated on daily basis, 20% of hours must be below.
    off_months: List[int] | None = (
        None  # Tuple of Month Numbers (1 = January) for months where heat pump is shut off entirely.
    )
    frac_exposed_to_hp: float  # fraction of the home that is open to the Heat Pump Indoor units (no doorway separating)
    frac_adjacent_to_hp: float  # fraction of the home that is adjacent to the space where the Heat Pump Indoor units are located (one doorway away)
    doors_open_to_adjacent: bool  # True if doors are open to rooms adjoining those containing Heat Pump Indoor Units.
    bedroom_temp_tolerance: TemperatureTolerance  # 'low' - little temp drop allowed in back rooms,  'med' - 5 deg F cooler is OK, 'high' - 10 deg F cooler is OK
    serves_garage: bool = False  # True if garage is heated by heat pump.


class ConventionalHeatingSystem(BaseModel):
    """Describes a non-heat-pump heating system"""

    heat_fuel_id: (
        int  # ID of heating system fuel type (use Library fuels() method for IDs)
    )
    heating_effic: float  # 0 - 1.0 seasonal heating efficiency
    aux_elec_use: float  # Auxiliary fan/pump/controls electric use, expressed as kWh/(MMBTU heat delivered)
    frac_load_served: float = 1.0   # fraction of heating load served by this system

class EnergyPrices(BaseModel):
    """Fuel and Electricity prices. Also, includes CO2 intensity for the electric utility """

    utility_id: int  # ID of the electric utility rate schedule serving the building

    # kWh limit per month for PCE assistance. Set to 0 if no PCE for bldg, or None if no limit to the
    # PCE the building can receive (e.g. community building)
    pce_limit: float | None = 750.0

    elec_rate_override: float | None = (
        None  # If provided, overrides the electric energy and demand
    )         #    charges in the Utility rate schedule
    
    pce_rate_override: float | None = (
        None  # Overrides the PCE rate in the Utility rate schedule
    )

    customer_charge_override: float | None = None  # Overrides Utility customer charge

    co2_lbs_per_kwh_override: float | None = (
        None  # Overrides Utility CO2 pounds per kWh of Utility electricity
    )

    # Fuel price overrides. Default fuel prices are associated with the City where the 
    # building is located. The prices below override those values.
    # This is a dictionary of overrides. The key is the Fuel ID, and the value is the 
    # override price. If a key does not exist for a fuel, that means the price is not overridden.
    fuel_price_overrides: dict[int, float] = {}

    sales_tax_override: float | None = (
        None  # Overrides sales tax (city + borough) for the city
    )


class BuildingDescription(BaseModel):
    """Description of Building."""

    city_id: int  # ID of City being modeled (use Library cities() method for IDs)

    energy_prices: EnergyPrices    # Energy price information for the building

    # Description of non-heat-pump heating systems: primary and secondary (optional)
    conventional_heat: Tuple[ConventionalHeatingSystem, ConventionalHeatingSystem | None]

    heat_pump: HeatPump | None = (
        None  # Description of Heat Pump. If None, then no heat pump.
    )

    building_type: BuildingType = (
        BuildingType.residential
    )  # Type of building, relevant for PCE
    #    applicability and limits.

    garage_stall_count: int  # 0: No garage, 1: 1-car garage.  Max is 4.
    bldg_floor_area: (
        float  # Floor area in square feet of home living area, not counting garage.
    )
    occupant_count: float = 3.0    # Number of occupants for estimating non-space energy use
    indoor_heat_setpoint: float = 70.0  # Indoor heating setpoint, deg F
    ua_per_ft2: float    # UA per square foot for main home

    dhw_fuel_id: int | None = None       # ID of domestic hot water fuel
    dhw_ef: float                     # Energy Factor of DHW System
    clothes_drying_fuel_id: int | None = None   # ID of clothes drying fuel
    cooking_fuel_id: int | None = None   # ID of cooking fuel
    ev_charging: EVCharging             # Type of Home EV charging

    # *** Need to have miscellaneous lights and appliances info here


class TimePeriodResults(BaseModel):
    period: str  # time period being reported on, e.g. "Jan" for January, "Annual" for full year
    hp_load_mmbtu: float  # space heat load in MMBTU served by heat pump
    hp_load_frac: float  # fraction of the space heat load served by the heat pump
    hp_kwh: float  # kWh consumed by heat pump
    hp_capacity_used_max: float  # Fraction of the heat pump capacity used, maximum, 0 - 1.0
    cop: float | None  # average heat pump COP for the period

    conventional_load_mmbtu: float   # total space heat load in MMBTU served by conventional systems
    conventional_load_mmbtu_by_sys: (
        Tuple[float, float]  # space heat load in MMBTU served by conventional heating systems, split (primary, secondary)
    )

    # Fuel use in MMBTU by Fuel ID and End Use.
    # Outer key is Fuel ID string, inner key is energy end-use ID string
    # Value is fuel use expressed in MMBTU (remember electricity is in MMBTU also)
    fuel_use_mmbtu: dict[Fuel, dict[EndUse, float]]

    # Electric coincident peak demand in kW
    elec_demand: float

    # Fuel use expressed in fuel units (e.g. gallons) by Fuel ID and End Use
    fuel_use_units: dict[Fuel, dict[EndUse, float]]

    # Fuel Cost by Fuel ID
    fuel_cost: dict[Fuel, float]

    # Total Fuel and Electricity costs
    fuel_total_cost: float | None = None


class DetailedModelResults(BaseModel):
    """Model results with monthly and annual aggregate detail."""

    monthly_results: List[TimePeriodResults]  # monthly totals of key modeling results
    annual_results: TimePeriodResults  # Annual totals of key modeling results
    design_heat_temp: float  # 99% design heating temperature, deg F
    design_heat_load: float  # 99% design heating load, BTU/hour


# ---------------------------------------------

# Models related to Heat Pump analysis.


class RetrofitCost(BaseModel):
    """Cost information about installing, operating, and potentially financing
    a building retrofit, usually a heat pump retrofit.
    """

    capital_cost: float  # Installation cost, $
    rebate_amount: float = 0.0  # Rebate $ available to offset installation cost
    retrofit_life: int = 14  # Life of heat pump in years
    op_cost_chg: float = (
        0.0  # Change in annual heating system operating cost due to use of
    )
    #    heat pump. A positive value means increase in operating cost.
    frac_financed: float = (
        0.0  # Fraction of the (capital_cost - rebate_amount) that is financed, 0 - 1.0
    )
    loan_term: int | None = None  # Length of loan in years
    loan_interest: float | None = (
        None  # Loan interest rate, expressed as fraction, e.g. 0.055 for 5.5%
    )


class EconomicInputs(BaseModel):
    """Inputs related to fuel and electricity costs and economic analysis factors."""

    # If this value is single floating point number, then it is considered to be the escalation
    # rate of electric prices, e.g. 0.03 means 3% / year escalation.  If it is a list of values, then
    # it is considered to be a list of electric price multipliers for the years spanning the life
    # the of the heat pump. If the list is shorter than the life, the last value is extended for
    # the missing years. An example would be [1.0, 1.03, 1.05, 1.08, 1.10].
    elec_rate_forecast: float | List[float] = 0.023

    # If this value is single floating point number, then it is considered to be the escalation
    # rate of fuel prices, e.g. 0.03 means 3% / year escalation.  If it is a list of values, then
    # it is considered to be a list of fuel price multipliers for the years spanning the life
    # the of the heat pump. If the list is shorter than the life, the last value is extended for
    # the missing years.
    # This same escalation pattern is applied to all non-electric fuel prices
    fuel_price_forecast: float | List[float] = 0.033

    # Economic discount rate, nominal, as a fraction for Present Value calculations.
    # 0.0537 equates to 3% real with a 2.3% inflation rate.
    discount_rate: float = 0.0537

    # General inflation rate, expressed as a fraction, 0.023 for 2.3% / year
    inflation_rate: float = 0.023  


class ActualFuelUse(BaseModel):
    """This model describes the actual fuel and electricity use of the building assuming
    *no* heat pump, so the electricity use is actual use prior to installing a heat pump.
    """

    # This is the annual amount of fuel used by the building, the fuel being the type used for space
    # heating.  Express this value in the normal units used for the fuel, e.g. gallons for oil.
    secondary_fuel_units: float | None = None

    # If the above "fuel" use was for an electrically-heated home, this field should be set to True if the
    # fuel use value given (kWh) was just for space heating (no lights & other applicances).
    annual_electric_is_just_space_heat: bool = False

    # A 12-element list of the monthly electricity use of the building in kWh. If None, code will estimate values.
    electric_use_by_month: List[float | None] | None = None


class RetrofitAnalysisInputs(BaseModel):
    """Describes all the inputs used the analysis of the retrofit"""

    bldg_name: str = ""  # Building Name
    notes: str = ""  # Notes about the analysis
    pre_bldg: BuildingDescription  # Inputs describing the existing, pre-retrofit building.
    post_bldg: BuildingDescription  # Inputs describing the post-retrofit building.
    retrofit_cost: RetrofitCost  # Inputs describing the cost of installing and operating the heat pump
    economic_inputs: (
        EconomicInputs  # Fuel and Electricity price inputs and general economic inputs.
    )

class MiscRetrofitResults(BaseModel):
    # the multiplicative factor applied to building UA value in order to match the actual fuel
    # consumption of the building
    ua_true_up: float

    # reduced pounds per year of CO2 emissions due to heat pump use
    co2_lbs_saved: float

    # the annual driving mile equivalent of the above CO2 reduction
    co2_driving_miles_saved: float

    # the incremental price of the heating fuel being avoided, including sales tax
    fuel_price_incremental: float | None

    # the incremental price of the electricity used by the heat pump
    elec_rate_incremental: float


class RetrofitAnalysisResults(BaseModel):
    """Results from the analysis of installing a heat pump."""

    misc: MiscRetrofitResults  # miscellaneous results
    financial: CashFlowAnalysis  # cash flow and financial results for heat pump install
    base_case_detail: (
        DetailedModelResults  # monthly and annual detail on the existing, pre-retrofit case
    )
    with_retrofit_detail: (
        DetailedModelResults  # monthly and annual detail on the post-retrofit case
    )
    change_detail: DetailedModelResults  # the changes that occur going from the pre- to post-retrofit case


# ------- SAMPLE DATA -------

# For HeatPumpAnalysisinputs
"""
{
	"bldg_model_inputs": {
		"city_id": 1,
		"heat_pump": {
			"hspf_type": "hspf",
			"hspf": 13.25,
			"max_out_5f": 11000,
			"low_temp_cutoff": 5,
			"off_months": null,
			"frac_exposed_to_hp": 0.4,
			"frac_adjacent_to_hp": 0.25,
			"doors_open_to_adjacent": true,
			"bedroom_temp_tolerance": "low",
			"serves_garage": false
		},
		"exist_heat_system": {
			"heat_fuel_id": 2,
			"heating_effic": 0.8,
			"aux_elec_use": 3.0,
			"serves_dhw": true,
			"serves_clothes_drying": true,
			"serves_cooking": true,
			"occupant_count": 2.3
		},
		"bldg_floor_area": 3600,
		"garage_stall_count": 2,
		"indoor_heat_setpoint": 70,
		"insul_level": "wall2x6plus"
	},
	"heat_pump_cost": {
		"capital_cost": 4500,
		"rebate_amount": 1000
	},
	"economic_inputs": {
		"utility_id": 1
	},
	"actual_fuel_use": {
		"secondary_fuel_units": 1600.0
	}
}
"""
