from poynt.token import exchange_authorization_code, get_catalogs

import os
import secrets
from urllib.parse import urlencode


from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

from auth import hash_password, verify_password
from database import Base, SessionLocal, engine
from models import User, PoyntConnection

load_dotenv()

POYNT_APP_ID = os.environ["POYNT_APP_ID"]
POYNT_AUTHORIZE_URL = os.environ["POYNT_AUTHORIZE_URL"]
POYNT_REDIRECT_URI = os.environ["POYNT_REDIRECT_URI"]

app = FastAPI(title="Codelian Poynt")
Base.metadata.create_all(bind=engine)

is_production = os.getenv("ENVIRONMENT") == "production"

app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ["SESSION_SECRET"],
    https_only=is_production,
    same_site="lax"
)


templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):

    if request.session.get("user_id"):
        return RedirectResponse(
            "/dashboard",
            status_code=303
        )

    return RedirectResponse(
        "/login",
        status_code=303
    )


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="register.html"
    )


@app.post("/register")
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


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="login.html"
    )


@app.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...)
):

    email = email.strip().lower()

    with SessionLocal() as session:

        user = session.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()

        if not user or not verify_password(
            password,
            user.password_hash
        ):

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


@app.post("/logout")
async def logout(request: Request):

    request.session.clear()

    return RedirectResponse(
        "/login",
        status_code=303
    )


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

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user
        }
    )

@app.get("/oauth/start")
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

@app.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(
    request: Request,
    code: str | None = None,
    status: str | None = None,
    context: str | None = None,
    businessId: str | None = None,
):
    user_id = request.session.get("user_id")

    if not user_id:
        return HTMLResponse(
            "<h1>OAuth Error</h1>"
            "<p>Your Codelian login session could not be found.</p>",
            status_code=401
        )
    
    expected_context = request.session.get(
        "poynt_oauth_context"
    )

    if not expected_context:
        return HTMLResponse(
            "<h1>OAuth Error</h1>"
            "<p>No OAuth session was found.</p>",
            status_code=400
        )

    if not context or not secrets.compare_digest(
        context,
        expected_context
    ):
        return HTMLResponse(
            "<h1>OAuth Error</h1>"
            "<p>OAuth context validation failed.</p>",
            status_code=400
        )

    if not status or status.lower() != "success":
        return HTMLResponse(
            f"""
            <h1>Poynt Authorization</h1>
            <p>Authorization was not completed.</p>
            <p>Status: {status or "unknown"}</p>
            """,
            status_code=400
        )

    if not code:
        return HTMLResponse(
            "<h1>OAuth Error</h1>"
            "<p>Poynt did not provide an authorization code.</p>",
            status_code=400
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
        print(
            f"Poynt token request failed: {type(e).__name__}: {e}",
            flush=True
        )

        return HTMLResponse(
            """
            <h1>Poynt Token Error</h1>
            <p>
                Poynt authorization succeeded, but the
                merchant token request failed.
            </p>
            <p>
                Check the Render/application logs.
            </p>
            """,
            status_code=502
        )

    if not businessId:
        return HTMLResponse(
            "<h1>Poynt Error</h1>"
            "<p>No business ID was returned.</p>",
            status_code=400,
        )

    with SessionLocal() as session:
        connection = session.query(PoyntConnection).filter(
            PoyntConnection.user_id == user_id
        ).one_or_none()

        if connection:
            connection.business_id = businessId
            connection.access_token = access_token
            connection.refresh_token = token_response.get("refreshToken")
            connection.token_type = token_response.get("tokenType")

            expires_in = token_response.get("expiresIn")

            if expires_in:
                from datetime import datetime, timedelta

                connection.expires_at = (
                    datetime.utcnow()
                    + timedelta(seconds=int(expires_in))
                )

        else:
            from datetime import datetime, timedelta

            expires_in = token_response.get("expiresIn")

            expires_at = None

            if expires_in:
                expires_at = (
                    datetime.utcnow()
                    + timedelta(seconds=int(expires_in))
                )

            connection = PoyntConnection(
                user_id=user_id,
                business_id=businessId,
                access_token=access_token,
                refresh_token=token_response.get("refreshToken"),
                token_type=token_response.get("tokenType"),
                expires_at=expires_at,
            )

            session.add(connection)

        session.commit()

    catalogs = await get_catalogs(
        access_token,
        businessId,
    )

    return HTMLResponse(
        f"""
        <h1>Poynt API Success!</h1>
        <p>Merchant token exchange succeeded.</p>
        <p>Catalog API call succeeded.</p>
        <p>Business ID: {businessId}</p>
        <p>Catalog response received.{catalogs}</p>
        """
    )
    

@app.get("/debug/poynt-jwt")
async def debug_poynt_jwt():
    from poynt.token import create_self_signed_jwt

    token = create_self_signed_jwt()

    return {
        "created": True,
        "jwt_length": len(token)
    }

@app.get("/health")
async def health():

    return {
        "status": "healthy"
    }