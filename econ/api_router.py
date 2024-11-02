"""Defines the API for Economic analysis functions."""
from typing import List, Dict
from fastapi import APIRouter

from . import econ
from .models import CashFlowInputs, CashFlowAnalysis

router = APIRouter()

@router.post("/econ/analyze-cash-flows", response_model=CashFlowAnalysis, tags=['Economic Analysis'])
async def analyze_cash_flow(flows: CashFlowInputs) -> CashFlowAnalysis:
    return econ.analyze_cash_flow(flows)
