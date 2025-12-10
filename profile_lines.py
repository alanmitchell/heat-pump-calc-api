'''
This script does line profiling of the energy.energy_model.model_building function.
Need to ensure that the "dev" dependencies are installed.

Run this line profiling script with:

    uv run kernprof -l profile_lines.py

Then inspect results with:

    uv run python -m line_profiler -rmt profile_lines.py.lprof
'''

import time
import library.library as lib
from library.models import Fuel_id
print('importing library')
time.sleep(3.0)

# seed the caches with our test run
lib.tmy_from_id(702730, True)   
lib.tmy_df_from_id(702730)
lib.city_from_id(1)
lib.fuel_from_id(Fuel_id.elec)
lib.fuel_from_id(Fuel_id.oil1)
lib.fuel_from_id(Fuel_id.propane)

from json import loads
from energy.energy_model import model_building
from energy.models import BuildingDescription

bldg_json = """
{
	"city_id": 1,
	"energy_prices": {
		"utility_id": 1
	},
	"conventional_heat": [
		{
			"heat_fuel_id": "oil1",
			"heating_effic": 0.79,
			"aux_elec_use": 4.5,
			"frac_load_served": 0.75
		},
		{
			"heat_fuel_id": "propane",
			"heating_effic": 0.82,
			"aux_elec_use": 5.5,
			"frac_load_served": 0.25
		}
	],
	"heat_pump": null,
	"garage_stall_count": 2,
	"bldg_floor_area": 3600,
	"occupant_count": 2.3,
	"indoor_heat_setpoint": 70,
	"ua_per_ft2": 0.19,
	"dhw_fuel_id": "propane",
	"dhw_ef": 0.62,
	"clothes_drying_fuel_id": "elec",
	"cooking_fuel_id": "elec",
	"misc_elec_kwh_per_day": 14.0,
	"misc_elec_seasonality": 0.15,
	"ev_charging_miles": 1000,
	"solar_kw": 2.85
}
"""

bldg_dict = loads(bldg_json)
bldg = BuildingDescription(**bldg_dict)
print(model_building(bldg))