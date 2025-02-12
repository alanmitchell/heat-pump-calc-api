"""Defines the API for the Space Heat and Heat Pump modeling functions."""

from fastapi import APIRouter

from . import home_heat_model as heat
from . import heat_pump_analysis as analyze
from .models import (
    HeatModelInputs,
    DetailedModelResults,
    HeatPumpAnalysisInputs,
    HeatPumpAnalysisResults,
)

router = APIRouter()


@router.post(
    "/heat/model-space-heat",
    response_model=DetailedModelResults,
    tags=["Heating Models"],
)
async def model_space_heat(inp: HeatModelInputs) -> DetailedModelResults:
    return heat.model_space_heat(inp)


@router.post(
    "/heat/analyze-heat-pump",
    response_model=HeatPumpAnalysisResults,
    tags=["Heating Models"],
)
async def analyze_heat_pump(inp: HeatPumpAnalysisInputs) -> HeatPumpAnalysisResults:
    return analyze.analyze_heat_pump(inp)


"""

Sample JSON Input Data for model-space-heat:

{
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
    "heat_fuel_id": 3,
    "heating_effic": 0.8,
    "aux_elec_use": 3.0
  },
  "bldg_floor_area": 3600,
  "garage_stall_count": 2,
  "indoor_heat_setpoint": 70,
  "insul_level": "wall2x6plus",
  "ua_true_up": 1.0
}

"""
