# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a FastAPI-based REST API for modeling heat pump performance and economics in Alaskan communities. It models energy use before/after heat pump installation and performs economic analysis (NPV, IRR, payback) for retrofits.

## Commands

### Run the development server
```bash
uvicorn app:app --reload --port 8080
```

### Run production server (as in Procfile)
```bash
gunicorn -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8080 --worker-tmp-dir /dev/shm app:app
```

### Run library tests
```bash
cd bin && python test_library.py
```

### Lint
```bash
ruff check .
```

### Install dependencies
```bash
uv sync
```

## Architecture

The app is structured as a FastAPI application (`app.py`) that wires together three API modules:

### `/lib/*` — Library (`library/`)
Provides read-only reference data for Alaskan communities: cities, electric utilities, fuel types/prices, and TMY (Typical Meteorological Year) weather datasets. Data is fetched from a remote GitHub repository (`alanmitchell/akwlib-export`) and cached in memory with a 12-hour refresh interval (`library/library.py`). The `/lib/refresh` endpoint forces a reload.

### `/energy/*` — Energy Models (`energy/`)
Three endpoints:
- `POST /energy/energy-model` — simulates monthly/annual space heating energy use for a building, with or without a heat pump (`energy_model.py`)
- `POST /energy/fit-model` — fits an energy model to observed utility bill data (`fit_model.py`)
- `POST /energy/analyze-retrofit` — full pre/post retrofit comparison combining energy modeling with economic analysis (`retrofit_analysis.py`)

The core `HomeHeatModel` class in `energy_model.py` uses TMY hourly weather data, building heat-loss parameters, and heat pump performance curves to compute monthly energy use. It supports air-source and ground-source heat pumps, domestic hot water heat pumps, and optional garage heating.

Heat pump COP/capacity vs. outdoor temperature curves are handled in `energy/heat_pump_performance.py`. Model fitting to utility bills is in `energy/fit_model.py`.

### `/econ/*` — Economic Analysis (`econ/`)
A single endpoint `POST /econ/analyze-cash-flows` takes a list of cash flow items (initial amounts, escalating flows, pattern flows, periodic amounts) and returns IRR, NPV, discounted/simple payback, and B/C ratio. Used internally by `energy/retrofit_analysis.py` to compute heat pump economics.

### `general/`
Shared utilities:
- `utils.py` — helper functions for NaN handling, Pydantic↔DataFrame conversions
- `models.py` — shared Pydantic models (`Choice`, `Version`, `Message`)
- `dict2d.py` — a 2D dictionary utility used in energy modeling

### Key data flow for retrofit analysis
`RetrofitAnalysisInputs` → `energy_model.model_building()` (pre and post) → compute fuel savings → build `CashFlowInputs` → `econ.analyze_cash_flow()` → `RetrofitAnalysisResults`

## Deployment

Deployed on DigitalOcean App Platform. The `Procfile` defines the production startup command using gunicorn with uvicorn workers.
