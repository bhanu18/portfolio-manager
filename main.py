from fastapi import FastAPI
from routers import assets, trades, reports


app = FastAPI()

app.include_router(assets.router)
app.include_router(trades.router)
app.include_router(reports.router)

@app.get("/")
async def read_root():
    """
    Home endpoint for the Asset Management API.
    """
    welcome_message = "Welcome to the Asset Management API!🔥"
    return {"message": welcome_message}