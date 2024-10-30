from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

import library.api_router
import heat.api_router
import econ.api_router
from general.models import Version

VERSION = '0.1'
VERSION_DATE = '2024-10-11'

description = """
The Alaska Heat Pump Calculator API allows for modeling of heat pump performance
and economics in Alaskan communities. The API also allows for retrieval of fuel
and climate information for Alaskan communities.  The basic community information
is available through the /lib/* API endpoints.
"""

tags_metadata = [
    {
        "name": "General",
        "description": "General API information",
    },
    {
        "name": "Library",
        "description": "Alaskan Community and Fuel information.",
    },
    {
        "name": "Heating Models",
        "description": "Space Heating and Heat Pump Models."
    },
    {
        "name": "Economic Analysis",
        "description": "Economic Analysis Functions"
    }
]

app = FastAPI(
    title="Alaska Heat Pump Calculator API",
    description=description,
    version = VERSION,
    openapi_tags=tags_metadata
)

@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Hello from the Alaska Heat Pump Calculator API!"}

@app.get("/version", response_model=Version, tags=['General'])
async def version() -> Version:
    return Version(version=VERSION, version_date=VERSION_DATE)

# configure static files for the app
app.mount('/static', StaticFiles(directory='static'), name='static')

# routes that related to the Energy Library database supporting the app, including
# city, utility, weather, and fuel information.
app.include_router(library.api_router.router)

# routes to heating and heat pump models.
app.include_router(heat.api_router.router)

# routes to economic analysis functions.
app.include_router(econ.api_router.router)
