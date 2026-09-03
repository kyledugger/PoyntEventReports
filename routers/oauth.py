from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
from urllib.parse import urlencode


from poynt.token import exchange_authorization_code

from dotenv import load_dotenv
import os
import secrets
from poynt.connection import (
    get_poynt_connection,
    get_poynt_credentials,
    save_poynt_connection,
)


dotenv_file = os.getenv("DOTENV_FILE", ".env")
load_dotenv(dotenv_file)

from logging_config import configure_logging

import logging
logger = logging.getLogger(__name__)

POYNT_REDIRECT_URI = os.environ["POYNT_REDIRECT_URI"]
POYNT_APP_ID = os.environ["POYNT_APP_ID"]
POYNT_AUTHORIZE_URL = os.environ["POYNT_AUTHORIZE_URL"]

router = APIRouter()

templates = Jinja2Templates(directory="templates")

@router.get("/oauth/start")
async def oauth_start(request: Request):

    user_id = request.session.get("user_id")

    if not user_id:
        return RedirectResponse(
            "/login",
            status_code=303
        )

    # Generate a random value that will come back from Poynt
    context = secrets.token_urlsafe(32)

    # Remember which Codelian session initiated this OAuth request
    request.session["poynt_oauth_context"] = context

    params = {
        "client_id": POYNT_APP_ID,
        "redirect_uri": POYNT_REDIRECT_URI,
        "context": context,
    }

    authorization_url = (
        f"{POYNT_AUTHORIZE_URL}?{urlencode(params)}"
    )

    return RedirectResponse(
        authorization_url,
        status_code=303
    )

@router.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(
    request: Request,
    code: str | None = None,
    status: str | None = None,
    context: str | None = None,
    businessId: str | None = None,
):
    user_id = request.session.get("user_id")

    if not user_id:
        return templates.TemplateResponse(
            request=request,
            name="message.html",
            context={
                "title": "OAuth Error",
                "paragraphs": [
                    "Your Codelian login session could not be found."
                ],
                "show_dashboard_link": False,
            },
            status_code=401,
        )
    
    expected_context = request.session.get(
        "poynt_oauth_context"
    )

    if not expected_context:
        return templates.TemplateResponse(
            request=request,
            name="message.html",
            context={
                "title": "OAuth Error",
                "paragraphs": [
                    "No OAuth session was found."
                ],
                "show_dashboard_link": False,
            },
            status_code=400,
        )

    if not context or not secrets.compare_digest(
        context,
        expected_context
    ):
        return templates.TemplateResponse(
            request=request,
            name="message.html",
            context={
                "title": "OAuth Error",
                "paragraphs": [
                    "OAuth context validation failed."
                ],
                "show_dashboard_link": False,
            },
            status_code=400,
        )

    if not status or status.lower() != "success":
        return templates.TemplateResponse(
            request=request,
            name="message.html",
            context={
                "title": "Poynt Authorization",
                "paragraphs": [
                    "Authorization was not completed.",
                    f"Status: {status or 'unknown'}",
                ],
                "show_dashboard_link": False,
            },
            status_code=400,
        )

    if not code:
        return templates.TemplateResponse(
            request=request,
            name="message.html",
            context={
                "title": "OAuth Error",
                "paragraphs": [
                    "Poynt did not provide an authorization code."
                ],
                "show_dashboard_link": False,
            },
            status_code=400,
        )

    # OAuth response is valid.
    # Consume the context so it cannot be reused.
    request.session.pop("poynt_oauth_context", None)

    try:
        token_response = await exchange_authorization_code(
            code=code,
            redirect_uri=POYNT_REDIRECT_URI,
        )

        access_token = token_response["accessToken"]

    except Exception as e:
        logger.error(
            "Poynt catalog request failed: %s",
            e,
        )

        return templates.TemplateResponse(
            request=request,
            name="message.html",
            context={
                "title": "Poynt Token Error",
                "paragraphs": [
                    "Poynt authorization succeeded, but the merchant token request failed.",
                    "Check the Render/application logs.",
                ],
                "show_dashboard_link": False,
            },
            status_code=502,
        )

    if not businessId:
        return templates.TemplateResponse(
            request=request,
            name="message.html",
            context={
                "title": "Poynt Error",
                "paragraphs": [
                    "No business ID was returned."
                ],
                "show_dashboard_link": False,
            },
            status_code=400,
        )

    expires_in = token_response.get("expiresIn")

    expires_at = None

    if expires_in:
        expires_at = (
            datetime.utcnow()
            + timedelta(seconds=int(expires_in))
        )

    save_poynt_connection(
        user_id=user_id,
        business_id=businessId,
        access_token=access_token,
        refresh_token=token_response.get("refreshToken"),
        token_type=token_response.get("tokenType"),
        expires_at=expires_at,
    )
    return RedirectResponse(
        "/dashboard",
        status_code=303
    )        
