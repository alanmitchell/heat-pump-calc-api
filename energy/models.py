"""Models associated with the home energy and heat pump calculations."""

from typing import List, Tuple
from enum import Enum

from pydantic import BaseModel

from library.models import Fuel_id
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

class TemperatureTolerance(str, Enum):
    """Describes amount of indoor temperature drop that is considered acceptable."""

    low = "low"  # only a small drop is acceptable
    med = "med"  # 5 deg F drop is acceptable
    high = "high"  # 10 deg F drop is acceptable

class EndUse(str, Enum):
    """Energy End Uses addressed by model"""
    space_htg = "space_htg"    # space heating
    dhw = "dhw"                # domestic hot water
    cooking = "cooking"        # cooking
    drying = "drying"          # drying
    misc_elec = "misc_elec"    # other electric lights and appliances
    ev_charging = "ev_charging"   # Home charging of EVs
    pv_solar = 'pv_solar'      # Photovoltaic solar production (shown as a negative value)

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

    heat_fuel_id: Fuel_id | None = None  # ID of heating system fuel type
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
    fuel_price_overrides: dict[Fuel_id, float] = {}

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

    garage_stall_count: int  # 0: No garage, 1: 1-car garage.  Max is 4.
    bldg_floor_area: (
        float  # Floor area in square feet of home living area, not counting garage.
    )
    occupant_count: float = 3.0    # Number of occupants for estimating non-space energy use
    indoor_heat_setpoint: float = 70.0  # Indoor heating setpoint, deg F
    ua_per_ft2: float    # UA per square foot for main home

    dhw_fuel_id: Fuel_id | None = None       # ID of domestic hot water fuel
    dhw_ef: float = 0.62                     # Energy Factor of DHW System
    clothes_drying_fuel_id: Fuel_id | None = None   # ID of clothes drying fuel
    cooking_fuel_id: Fuel_id | None = None   # ID of cooking fuel

    # annual average kWh/day for lights and miscellaneous appliances end uses. 
    # Does not include space htg, dhw, cooking, and clothes drying, EV charging, or solar.
    misc_elec_kwh_per_day: float = 13.0

    # +/- deviation in use/day from average for December and June. 
    # Expressed as a fraction of the average. If positive
    # December is higher than average and June is lower. If negative,
    # December is lower than average and June higher (perhaps snowbird usage pattern)
    misc_elec_seasonality: float = 0.15  

    # Infomration about Home EV charging electricity use.
    ev_charging_miles_per_day: float = 0.0           # average miles / day of home EV charging
    ev_miles_per_kwh: float = 3.0            # Average miles driven per kWh of charge
    ev_seasonality: float = 0.0              # Variation of Dec EV kWh/day compared to average, fraction
    
    solar_kw: float = 0.0                    # kW of home PV solar
    solar_kwh_per_kw: float = 700.0          # Annual kWh produced per solar kW installed


class TimePeriodResults(BaseModel):
    period: str  # time period being reported on, e.g. "Jan" for January, "Annual" for full year
    hp_load_mmbtu: float  # space heat load in MMBTU served by heat pump
    hp_load_frac: float  # fraction of the space heat load served by the heat pump
    hp_kwh: float  # kWh consumed by heat pump
    hp_capacity_used_max: float  # Fraction of the heat pump capacity used, maximum, 0 - 1.0
    cop: float | None  # average heat pump COP for the period

    conventional_load_mmbtu: float   # total space heat load in MMBTU served by conventional systems
    conventional_load_mmbtu_primary: float    # space heat load in MMBTU for primary conventional system
    conventional_load_mmbtu_secondary: float    # space heat load in MMBTU for secondary conventional system

    # Fuel use in MMBTU by Fuel ID and End Use.
    # Outer key is Fuel ID string, inner key is energy end-use ID string
    # Value is fuel use expressed in MMBTU (remember electricity is in MMBTU also)
    fuel_use_mmbtu: dict[Fuel_id, dict[EndUse, float]]

    # Electric coincident peak demand in kW
    elec_demand: float

    # Fuel use expressed in fuel units (e.g. gallons) by Fuel ID and End Use
    fuel_use_units: dict[Fuel_id, dict[EndUse, float]]

    # Fuel Cost by Fuel ID
    fuel_cost: dict[Fuel_id, float]

    # Total Fuel and Electricity costs
    fuel_total_cost: float | None = None

    # CO2 emissions due to the fuel use for the period
    co2_lbs: float    # pounds of CO2 emitted from building fuel use


class DetailedModelResults(BaseModel):
    """Model results with monthly and annual aggregate detail."""

    monthly_results: List[TimePeriodResults]  # monthly totals of key modeling results
    annual_results: TimePeriodResults  # Annual totals of key modeling results
    design_heat_temp: float  # 99% design heating temperature, deg F
    design_heat_load: float  # 99% design heating load, BTU/hour


class EnergyModelFitInputs(BaseModel):
    """Inputs needed to fin the Buildng Energy Model to actual Use data
    """
    # Description of the building; fit tuning characteristics do not need to be
    # included, as the fitting process will determine them.
    building_description: BuildingDescription

    # Fuel use in fuel units (not MMBTU) for each fuel used by the building,
    # except electricity, as that is addressed separately.
    actual_fuel_by_type: dict[Fuel_id, float]

    # A 12-element list of the monthly electricity use of the building in kWh.
    electric_use_by_month: List[float]

class EnergyModelFitOutput(BaseModel):
    """Results of fitting the energy model.
    """
    # The final building description with the best-fit parameters in the description.
    building_description: BuildingDescription

    # Fit information of each of the fuel types that building uses, including electricity.
    # The Tuple is (actual use, modeled use, model error fraction). Electricity is presented
    # on an annual total basis even though fitting used monthly values.
    fuel_fit_info: dict[Fuel_id, Tuple[float, float, float]]

# ---------------------------------------------

# Models related to Heat Pump analysis.


class RetrofitCost(BaseModel):
    """Cost information about installing, operating, and potentially financing
    a building retrofit, usually a heat pump retrofit.
    """

    capital_cost: float  # Installation cost, $
    rebate_amount: float = 0.0  # Rebate $ available to offset installation cost
    retrofit_life: int = 14  # Life of heat pump in years
    
    # Change in annual heating system operating cost due to the retrofit.
    # A positive value means increase in operating cost.
    op_cost_chg: float = 0.0
    
    loan_amount: float = 0.00      # Amount borrowed to finance the retrofit
    loan_term: int | None = None  # Length of loan in years

    # Loan interest rate, expressed as fraction, e.g. 0.055 for 5.5%
    loan_interest: float | None = None


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


class RetrofitAnalysisInputs(BaseModel):
    """Describes all the inputs used the analysis of the retrofit"""

    bldg_name: str = ""  # Building Name
    notes: str = ""  # Notes about the analysis
    pre_bldg: BuildingDescription  # Inputs describing the existing, pre-retrofit building.
    post_bldg: BuildingDescription  # Inputs describing the post-retrofit building.
    retrofit_cost: RetrofitCost  # Inputs describing the cost of installing and operating the heat pump
    economic_inputs: EconomicInputs  # General economic inputs.


class MiscRetrofitResults(BaseModel):

    # reduced pounds per year of CO2 emissions due to heat pump use
    co2_lbs_saved: float

    # the annual driving mile equivalent of the above CO2 reduction
    co2_driving_miles_saved: float


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
