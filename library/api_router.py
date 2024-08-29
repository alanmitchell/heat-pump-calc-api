from simplejson import dumps, loads
from fastapi import APIRouter

from . import library as lib

router = APIRouter()

@router.get("/lib/cities")
async def cities():
    return {'choices': lib.cities()}

@router.get("/lib/cities/{city_id}")
async def city(city_id: int):
    return loads(dumps(lib.city_from_id(city_id), ignore_nan=True))

@router.get("/lib/utilities")
async def utilities():
    return {'choices': lib.utilities()}

@router.get("/lib/utilities/{utility_id}")
async def utility(utility_id: int):
    return loads(dumps(lib.util_from_id(utility_id), ignore_nan=True))

@router.get("/lib/fuels")
async def fuels():
    return {'choices': lib.fuels()}

@router.get("/lib/fuels/{fuel_id}")
async def fuel(fuel_id: int):
    return loads(dumps(lib.fuel_from_id(fuel_id), ignore_nan=True))

@router.get("/lib/tmys")
async def tmys():
    return {'records': lib.tmys()}

@router.get("/lib/tmys/{tmy_id}")
async def tmy(tmy_id: int, site_info_only: bool = False):
    return lib.tmy_from_id(tmy_id, site_info_only)
