from fastapi import FastAPI, Request
import time
from routers import assets, trades, reports, auth, group, email


app = FastAPI(title="Portfolio Management API",
    description="API for managing assets, trades, and reports in a portfolio.",
    version="1.0.0") 

app.include_router(assets.router)
app.include_router(trades.router)
app.include_router(reports.router)
app.include_router(auth.router)
app.include_router(group.router)
app.include_router(email.router)

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """
    This middleware calculates the time taken to process a request
    and adds it to the response headers.
    """
    # Get the time before the endpoint is called
    start_time = time.time()
    
    # Proceed to call the actual endpoint
    response = await call_next(request)
    
    # Get the time after the endpoint has finished
    process_time = time.time() - start_time
    
    # Add the custom header to the response
    response.headers["X-Process-Time"] = str(process_time)
    
    return response

@app.get("/")
async def read_root():
    """
    Home endpoint for the Asset Management API.
    """
    welcome_message = "Welcome to mu fucking Asset Management API!🔥"
    return {"message": welcome_message}