from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from starlette.requests import Request

import library.api_router
import energy.api_router
import econ.api_router
from general.models import Version

VERSION = "0.2"
VERSION_DATE = "2025-11-19"

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
    {"name": "Energy Models", "description": "Energy Use and Heat Pump Models."},
    {"name": "Economic Analysis", "description": "Economic Analysis Functions"},
]

app = FastAPI(
    title="Alaska Heat Pump Calculator API",
    description=description,
    version=VERSION,
    openapi_tags=tags_metadata,
)

# make API very open and not subject to CORS restrictions.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # <-- allow all origins
    allow_credentials=False,   # must be False when using "*"
    allow_methods=["*"],       # allow all HTTP methods
    allow_headers=["*"],       # allow all request headers
)

# configure static files for the app
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates("templates")


@app.get("/", include_in_schema=False)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={})


# Define a route for the favicon
# @app.get("/favicon.ico", include_in_schema=False)
# async def favicon():
#    return FileResponse("/static/img/heat-pump.png")


@app.get("/version", response_model=Version, tags=["General"])
async def version() -> Version:
    return Version(version=VERSION, version_date=VERSION_DATE)


# routes that related to the Energy Library database supporting the app, including
# city, utility, weather, and fuel information.
app.include_router(library.api_router.router)

# routes to heating and heat pump models.
app.include_router(energy.api_router.router)

# routes to economic analysis functions.
app.include_router(econ.api_router.router)
