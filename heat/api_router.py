"""Defines the API for the Library functions."""
from fastapi import APIRouter

from . import home_heat_model as heat
from .models import HeatModelInputs, HeatModelResults

router = APIRouter()

@router.post("/heat/model-space-heat", response_model=HeatModelResults, tags=['Heating Models'])
async def model_space_heat(inp: HeatModelInputs) -> HeatModelResults:
    return heat.model_space_heat(inp)



"""

Sample JSON Input Data:

{
  "city_id": 1,
  "heat_pump": {
    "hspf_type": "hspf",
    "hspf": 13.5,
    "max_out_5f": 15000,
    "low_temp_cutoff": 5,
    "off_months": null
  },
  "exist_heat_system": {
    "heat_fuel_id": 3,
    "heating_effic": 0.8,
    "aux_elec_use": 1.5
  },
  "co2_lbs_per_kwh": 0.75,
  "garage_stall_count": 1,
  "garage_heated_by_hp": false,
  "bldg_floor_area": 1000,
  "indoor_heat_setpoint": 70,
  "insul_level": "wall2x6",
  "pct_exposed_to_hp": 0.5,
  "doors_open_to_adjacent": true,
  "bedroom_temp_tolerance": "low",
  "ua_true_up": 1
}


"""