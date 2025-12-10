"""Defines the API for the Space Heat and Heat Pump modeling functions."""

from fastapi import APIRouter

from . import energy_model as energy
from . import fit_model as fit
from . import retrofit_analysis as analyze
from .models import (
    BuildingDescription,
    DetailedModelResults,
    EnergyModelFitInputs,
    RetrofitAnalysisInputs,
    RetrofitAnalysisResults,
)

router = APIRouter()


@router.post(
    "/energy/energy-model",
    response_model=DetailedModelResults,
    tags=["Energy Models"],
)
async def model_building_energy(inp: BuildingDescription) -> DetailedModelResults:
    return energy.model_building(inp)

@router.post(
    "/energy/fit-model",
    response_model=BuildingDescription,
    tags=["Energy Models"],
)
async def fit_model(inp: EnergyModelFitInputs) -> BuildingDescription:
    return fit.fit_model(inp)


@router.post(
    "/energy/analyze-retrofit",
    response_model=RetrofitAnalysisResults,
    tags=["Energy Models"],
)
async def analyze_retrofit(inp: RetrofitAnalysisInputs) -> RetrofitAnalysisResults:
    return analyze.analyze_retrofit(inp)


"""

Sample JSON Input Data for model-space-heat:


"""
