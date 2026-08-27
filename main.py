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
from database import SessionLocal
from models import User


load_dotenv()

POYNT_APP_ID = os.environ["POYNT_APP_ID"]
POYNT_AUTHORIZE_URL = os.environ["POYNT_AUTHORIZE_URL"]
POYNT_REDIRECT_URI = os.environ["POYNT_REDIRECT_URI"]

app = FastAPI(title="Codelian Poynt")

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

    # The OAuth request has successfully returned to us.
    # We are intentionally NOT exchanging the code yet.

    request.session.pop("poynt_oauth_context", None)

    if status != "success":
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

    return HTMLResponse(
        """
        <h1>Poynt Authorization Received</h1>
        <p>Success!</p>
        <p>
            Codelian successfully received the authorization
            response from Poynt.
        </p>
        <p>
            The authorization code has NOT been exchanged yet.
        </p>
        <p>
            <a href="/dashboard">Return to Dashboard</a>
        </p>
        """
    )

@app.get("/health")
async def health():

    return {
        "status": "healthy"
    }