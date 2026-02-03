import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
import traceback

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from starlette.requests import Request

import library.api_router
import energy.api_router
import econ.api_router
from general.models import Version

VERSION = "0.4"
VERSION_DATE = "2025-12-08"

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

# ---- Configure loggers and exception handlers

ALASKA_TZ = ZoneInfo("America/Anchorage")

class AlaskaFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=ALASKA_TZ)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%d %H:%M:%S AK Time")

formatter = AlaskaFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(formatter)

logger = logging.getLogger("app")
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# Silence the uvicorn logger so we only get one traceback
uvicorn_error_logger = logging.getLogger("uvicorn.error")
uvicorn_error_logger.setLevel(logging.CRITICAL)

def alaska_now_str() -> str:
    """Return current time in Alaska timezone as a string string."""
    return datetime.now(ALASKA_TZ).strftime("%Y-%m-%d %H:%M:%S AK Time")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catches unhandled exceptions globally. Both responds to the 
    User and logs the error.
    """
    # Build full traceback string
    tb_str = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )

    # Log it – DO App Platform will capture this
    logger.error(
        "Unhandled exception in request %s %s\n%s",
        request.method,
        request.url.path,
        tb_str,
    )

    # Minimal info back to the client
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An error occurred in the Heat Pump Calculator API. Please contact the developer and report the following error time:",
            "timestamp": alaska_now_str(),
        },
    )

# ------------------ Routes below here

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
