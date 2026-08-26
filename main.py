from fastapi import FastAPI
from sqlalchemy import select

from database import Base, SessionLocal, engine
from models import AppStatus


app = FastAPI(title="Codelian Poynt")


Base.metadata.create_all(bind=engine)


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


@app.get("/database-test")
async def database_test():

    with SessionLocal() as session:

        status = AppStatus(
            message="Codelian PostgreSQL connection works!"
        )

        session.add(status)
        session.commit()

        result = session.execute(
            select(AppStatus)
            .order_by(AppStatus.id.desc())
        )

        latest = result.scalars().first()

        return {
            "database": "connected",
            "message": latest.message,
            "id": latest.id
        }