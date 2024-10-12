"""Defines the API for the Library functions."""
from typing import List

from simplejson import dumps, loads
from fastapi import APIRouter

from . import library as lib
from models.general import Choice
from library.models import (
    City, 
    Utility, 
    Fuel, 
    FuelPrice, 
    TMYmeta, 
    TMYdataset
)

router = APIRouter()

@router.get("/lib/cities", response_model=List[Choice])
async def cities() -> List[Choice]:
    return lib.cities()

@router.get("/lib/cities/{city_id}", response_model=City)
async def city(city_id: int) -> City:
    #return loads(dumps(lib.city_from_id(city_id), ignore_nan=True))
    return lib.city_from_id(city_id)

@router.get("/lib/utilities", response_model=List[Choice])
async def utilities() -> List[Choice]:
    return lib.utilities()

@router.get("/lib/utilities/{utility_id}", response_model=Utility)
async def utility(utility_id: int) -> Utility:
    return lib.util_from_id(utility_id)

@router.get("/lib/fuels", response_model=List[Choice])
async def fuels() -> List[Choice]:
    return lib.fuels()

@router.get("/lib/fuels/{fuel_id}", response_model=Fuel)
async def fuel(fuel_id: int) -> Fuel:
    return lib.fuel_from_id(fuel_id)

@router.get("/lib/fuelprice/{fuel_id}/{city_id}", response_model=FuelPrice)
async def fuel_price(fuel_id: int, city_id: int) -> FuelPrice:
    return lib.fuel_price(fuel_id, city_id)

@router.get("/lib/tmys", response_model=List[TMYmeta])
async def tmys() -> List[TMYmeta]:
    return lib.tmys()

@router.get("/lib/tmys/{tmy_id}", response_model=TMYdataset)
async def tmy(tmy_id: int, site_info_only: bool = False) -> TMYdataset:
    return lib.tmy_from_id(tmy_id, site_info_only)
