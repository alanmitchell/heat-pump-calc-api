from fastapi import FastAPI
from . import library
from simplejson import dumps, loads

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello from the Alaska Heat Pump Calculator API!"}

@app.get("/cities")
async def cities():
    return {'choices': library.cities()}

@app.get("/city/{city_id}")
async def city(city_id: int):
    return loads(dumps(library.city_from_id(city_id), ignore_nan=True))

@app.get("/utilities")
async def utilities():
    return {'choices': library.utilities()}

@app.get("/utility/{utility_id}")
async def utility(utility_id: int):
    return loads(dumps(library.util_from_id(utility_id), ignore_nan=True))

@app.get("/fuels")
async def fuels():
    return {'choices': library.fuels()}

@app.get("/fuel/{fuel_id}")
async def fuel(fuel_id: int):
    return loads(dumps(library.fuel_from_id(fuel_id), ignore_nan=True))

@app.get("/tmy/{tmy_id}")
async def tmy(tmy_id: int):
    return {'records': library.tmy_from_id(tmy_id)}

@app.get("/heating-design-temp/{tmy_id}")
async def heating_design_temp(tmy_id: int):
    return {'value': library.heating_design_temp(tmy_id)}
