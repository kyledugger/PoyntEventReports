from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from fastapi.templating import Jinja2Templates

from auth import hash_password, verify_password
from database import SessionLocal
from models import User, Organization, OrganizationMember

import os
from dotenv import load_dotenv

dotenv_file = os.getenv("DOTENV_FILE", ".env")
load_dotenv(dotenv_file)

from logging_config import configure_logging
import logging

logger = logging.getLogger(__name__)
configure_logging()

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
    organization_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...)
):
    organization_name = organization_name.strip()
    email = email.strip().lower()

    if not organization_name:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={
                "error": "Organization name is required.",
                "organization_name": organization_name,
                "email": email,
            },
            status_code=400
        )

    with SessionLocal() as session:
        existing_user = session.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()

        if existing_user:
            return templates.TemplateResponse(
                request=request,
                name="register.html",
                context={
                    "error": "An account with that email already exists.",
                    "organization_name": organization_name,
                    "email": email,
                },
                status_code=400
            )

        # User, organization, and owner membership are created
        # in the same transaction.
        user = User(
            email=email,
            password_hash=hash_password(password)
        )
        session.add(user)
        session.flush()

        organization = Organization(
            name=organization_name
        )
        session.add(organization)
        session.flush()

        membership = OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role="owner"
        )
        session.add(membership)

        session.commit()

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

        password_valid = (
            verify_password(password, user.password_hash)
            if user
            else False
        )

        logger.debug(
            "LOGIN: user found=%s, user_id=%s, password valid=%s",
            user is not None,
            user.id if user else None,
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
