from fastapi import FastAPI
from simplejson import dumps, loads
import library.library as lib

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello from the Alaska Heat Pump Calculator API!"}

@app.get("/cities")
async def cities():
    return {'choices': lib.cities()}

@app.get("/cities/{city_id}")
async def city(city_id: int):
    return loads(dumps(lib.city_from_id(city_id), ignore_nan=True))

@app.get("/utilities")
async def utilities():
    return {'choices': lib.utilities()}

@app.get("/utilities/{utility_id}")
async def utility(utility_id: int):
    return loads(dumps(lib.util_from_id(utility_id), ignore_nan=True))

@app.get("/fuels")
async def fuels():
    return {'choices': lib.fuels()}

@app.get("/fuels/{fuel_id}")
async def fuel(fuel_id: int):
    return loads(dumps(lib.fuel_from_id(fuel_id), ignore_nan=True))

@app.get("/tmys")
async def tmys():
    return {'records': lib.tmys()}

@app.get("/tmys/{tmy_id}")
async def tmy(tmy_id: int, site_info_only: bool = False):
    return lib.tmy_from_id(tmy_id, site_info_only)

