"""Defines the API for Economic analysis functions."""
from typing import List, Dict
from fastapi import APIRouter

from . import econ
from .models import Test1, Test2

router = APIRouter()

@router.post("/econ/test", tags=['Economic Analysis'])
async def test(inp: List[Test1 | Test2]) -> List[str]:

    return [str(type(it)) for it in inp]
