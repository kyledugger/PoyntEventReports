$env:DOTENV_FILE = ".env.local-prod-db"
uvicorn main:app --reload