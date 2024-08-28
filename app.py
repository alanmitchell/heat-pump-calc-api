from fastapi import FastAPI
try:
    import library
except:
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

@app.get("/tmys")
async def tmys():
    return {'records': library.tmys()}

@app.get("/tmy/{tmy_id}")
async def tmy(tmy_id: int):
    return library.tmy_from_id(tmy_id)

@app.get("/tmy-meta/{tmy_id}")
async def tmy_meta(tmy_id: int):
    return library.tmy_meta(tmy_id)

