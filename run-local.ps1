netstat -ano | findstr :8000
if ($LASTEXITCODE -eq 1) {
    $env:DOTENV_FILE = ".env"
    uvicorn main:app --reload
} else {
    "Failed Startup: There is a process running on port 8000 already"
}