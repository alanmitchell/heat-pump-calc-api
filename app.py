from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

import library.api_router
from models.general import Version

VERSION = '0.1'
VERSION_DATE = '2024-10-11'

description = """
The Alaska Heat Pump Calculator API allows to model heat pump performance
and economics in Alaskan communities. The API also allows for retrieval of fuel
and climate information for Alaskan communities.  The basic community information
is available through the /lib/* API endpoints.
"""
app = FastAPI(
    title="Alaska Heat Pump Calculator API",
    description=description,
    version = VERSION
)

tags_metadata = [
    {
        "name": "version",
        "description": "Retrieves API version information",
    },
]

@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Hello from the Alaska Heat Pump Calculator API!"}

@app.get("/version", response_model=Version, tags=['version'])
async def version() -> Version:
    return Version(version=VERSION, version_date=VERSION_DATE)

# configure static files for the app
app.mount('/static', StaticFiles(directory='static'), name='static')

# routes that related to the Energy Library database supporting the app, including
# city, utility, weather, and fuel information.
app.include_router(library.api_router.router)
