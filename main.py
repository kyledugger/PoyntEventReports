import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from database import Base, SessionLocal, engine
from models import User
from poynt.connection import (
    get_poynt_connection,
    get_poynt_credentials,
    save_poynt_connection,
)

from poynt.client import (
    PoyntClient,
    PoyntReauthorizationRequired,
)
from routers.auth_routes import router as auth_router
from routers.oauth import router as oauth_router
from routers.poynt import router as poynt_router

dotenv_file = os.getenv("DOTENV_FILE", ".env")
load_dotenv(dotenv_file)

from logging_config import configure_logging

import logging
logger = logging.getLogger(__name__)

configure_logging()

ENVIRONMENT = os.getenv("ENVIRONMENT", "local")

if ENVIRONMENT == "local-prod-db":
    logger.warning("============================================================")
    logger.warning("LOCAL APPLICATION")
    logger.warning("DATABASE: PRODUCTION")
    logger.warning("============================================================")
elif ENVIRONMENT == "production":
    logger.info("============================================================")
    logger.info("PRODUCTION APPLICATION")
    logger.info("DATABASE: PRODUCTION")
    logger.info("============================================================")
else:
    logger.info("============================================================")
    logger.info("LOCAL APPLICATION")
    logger.info("DATABASE: LOCAL")
    logger.info("============================================================")

POYNT_APP_ID = os.environ["POYNT_APP_ID"]
POYNT_AUTHORIZE_URL = os.environ["POYNT_AUTHORIZE_URL"]


app = FastAPI(title="Codelian Poynt")
app.include_router(auth_router)
app.include_router(oauth_router)
app.include_router(poynt_router)

Base.metadata.create_all(bind=engine)

is_production = os.getenv("ENVIRONMENT") == "production"
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ["SESSION_SECRET"],
    https_only=is_production,
    same_site="lax"
)


templates = Jinja2Templates(directory="templates")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):

    user_id = request.session.get("user_id")

    if not user_id:

        return RedirectResponse(
            "/login",
            status_code=303
        )

    with SessionLocal() as session:

        user = session.get(User, user_id)

        if not user:
            request.session.clear()

            return RedirectResponse(
                "/login",
                status_code=303
            )

    poynt_connection = get_poynt_connection(user_id)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user,
            "poynt_connection": poynt_connection
        }
    )



@app.get("/health")
async def health():

    return {
        "status": "healthy"
    }