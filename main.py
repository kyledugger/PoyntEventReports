from fastapi import FastAPI

app = FastAPI(title="Codelian Poynt")

@app.get("/")
async def root():
    return {
        "application": "Codelian Poynt",
        "message": "Hello World!"
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy"
    }