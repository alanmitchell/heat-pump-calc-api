from fastapi import FastAPI

import library.api_router

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello from the Alaska Heat Pump Calculator API!"}

@app.get("/version")
async def version():
    return {
        'version': '0.1',
        'version_date': '2024-08-28'
        }

# routes that related to the Energy Library database supporting the app, including
# city, utility, weather, and fuel information.
app.include_router(library.api_router.router)
