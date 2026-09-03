from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from auth import hash_password, verify_password
from database import SessionLocal
from models import User
from dotenv import load_dotenv
import os

dotenv_file = os.getenv("DOTENV_FILE", ".env")
load_dotenv(dotenv_file)

from logging_config import configure_logging

import logging
logger = logging.getLogger(__name__)

router = APIRouter()

templates = Jinja2Templates(directory="templates")


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="register.html"
    )


@router.post("/register")
async def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...)
):

    email = email.strip().lower()

    with SessionLocal() as session:

        existing_user = session.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()

        if existing_user:

            return templates.TemplateResponse(
                request=request,
                name="register.html",
                context={
                    "error": "An account with that email already exists."
                },
                status_code=400
            )

        user = User(
            email=email,
            password_hash=hash_password(password)
        )

        session.add(user)
        session.commit()
        session.refresh(user)

        request.session["user_id"] = user.id

    return RedirectResponse(
        "/dashboard",
        status_code=303
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="login.html"
    )


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...)
):

    email = email.strip().lower()

    logger.debug("LOGIN: submitted email=%r", email)

    with SessionLocal() as session:

        user = session.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()

        logger.debug(
            "LOGIN: user found=%s, user_id=%s",
            user is not None,
            user.id if user else None,
        )

        logger.debug(
            "Login user lookup: found=%s, user_id=%s",
            user is not None,
            user.id if user else None,
        )

        password_valid = (
            verify_password(password, user.password_hash)
            if user
            else False
        )

        logger.debug(
            "LOGIN: password valid=%s",
            password_valid,
        )

        if not user or not password_valid:

            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context={
                    "error": "Invalid email or password."
                },
                status_code=401
            )

        request.session["user_id"] = user.id

    return RedirectResponse(
        "/dashboard",
        status_code=303
    )


@router.post("/logout")
async def logout(request: Request):

    request.session.clear()

    return RedirectResponse(
        "/login",
        status_code=303
    )