from poynt.token import exchange_authorization_code

import os
import secrets
from urllib.parse import urlencode
from html import escape
import json

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware
from datetime import datetime, timedelta
from auth import hash_password, verify_password
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

load_dotenv()

from logging_config import configure_logging

import logging
logger = logging.getLogger(__name__)

configure_logging()

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

    poynt_connection = get_poynt_connection(user_id)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user,
            "poynt_connection": poynt_connection
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
        logger.error(
            "Poynt catalog request failed: %s",
            e,
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

@app.get("/poynt/catalog", response_class=HTMLResponse)
async def poynt_catalog(request: Request):

    user_id = request.session.get("user_id")

    if not user_id:
        return RedirectResponse(
            "/login",
            status_code=303
        )

    credentials = get_poynt_credentials(user_id)

    if not credentials:
        return HTMLResponse(
            """
            <h1>Poynt Error</h1>
            <p>No Poynt connection was found.</p>
            <p>
                <a href="/dashboard">Return to Dashboard</a>
            </p>
            """,
            status_code=404
        )

    try:
        client = PoyntClient(
            credentials,
            user_id=user_id,
        )

        catalogs = await client.get_catalogs()

    except PoyntReauthorizationRequired:
        return HTMLResponse(
            """
            <h1>Poynt Authorization Required</h1>
            <p>
                Your Poynt authorization has expired.
                Please reconnect your Poynt account.
            </p>
            <p>
                <a href="/dashboard">Return to Dashboard</a>
            </p>
            """,
            status_code=401,
        )

    except Exception as e:
        print(
            f"Poynt catalog request failed: "
            f"{type(e).__name__}: {e}",
            flush=True
        )

        return HTMLResponse(
            """
            <h1>Poynt Catalog Error</h1>
            <p>The catalog request failed.</p>
            <p>Check the application logs.</p>
            <p>
                <a href="/dashboard">Return to Dashboard</a>
            </p>
            """,
            status_code=502
        )

    return HTMLResponse(
        """
        <h1>Poynt Catalog Success!</h1>
        <p>Catalog request succeeded.</p>
        <p>
            The Poynt access token was retrieved from the
            database and used to make this request.
        </p>
        <p>
            <a href="/dashboard">Return to Dashboard</a>
        </p>
        """
    )

def get_order_intervals(orders):
    # Build chronological order interval data for Chart #1.
    # Each point represents the number of seconds since the
    # previous order. The timestamp belongs to the newer order.
    chronological_orders = list(reversed(orders))

    order_intervals = []

    previous_time = None

    for order in chronological_orders:
        created_at = order.get("createdAt")

        if not created_at:
            continue

        try:
            current_time = datetime.fromisoformat(
                created_at.replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            continue

        if previous_time is not None:
            interval_seconds = (
                current_time - previous_time
            ).total_seconds()

            order_intervals.append({
                "time": created_at,
                "seconds": interval_seconds,
            })

        previous_time = current_time

        return order_intervals

@app.get("/poynt/orders", response_class=HTMLResponse)
async def poynt_orders(request: Request):
    user_id = request.session.get("user_id")

    if not user_id:
        return RedirectResponse(
            "/login",
            status_code=303
        )

    credentials = get_poynt_credentials(user_id)

    if not credentials:
        return HTMLResponse(
            """
            <h1>Poynt Error</h1>
            <p>No Poynt connection was found.</p>
            <p>
                <a href="/dashboard">Return to Dashboard</a>
            </p>
            """,
            status_code=404
        )

    try:
        client = PoyntClient(
            credentials,
            user_id=user_id,
        )

        orders = await client.get_recent_orders(100)

    except PoyntReauthorizationRequired:
        return HTMLResponse(
            """
            <h1>Poynt Authorization Required</h1>
            <p>
                Your Poynt authorization has expired.
                Please reconnect your Poynt account.
            </p>
            <p>
                <a href="/dashboard">Return to Dashboard</a>
            </p>
            """,
            status_code=401,
        )

    except Exception as e:
        logger.error(
            "Poynt recent orders request failed: %s",
            e,
        )

        return HTMLResponse(
            """
            <h1>Poynt Orders Error</h1>
            <p>The recent orders request failed.</p>
            <p>Check the application logs.</p>
            <p>
                <a href="/dashboard">Return to Dashboard</a>
            </p>
            """,
            status_code=502
        )

    # Newest first.
    orders = sorted(
        orders,
        key=lambda order: order.get("createdAt", ""),
        reverse=True,
    )

    # Determine the time span represented by the orders.
    oldest_order_at = None
    newest_order_at = None
    order_span_minutes = None

    order_times = []

    for order in orders:
        created_at = order.get("createdAt")

        if not created_at:
            continue

        try:
            order_time = datetime.fromisoformat(
                created_at.replace("Z", "+00:00")
            )
            order_times.append(order_time)
        except (TypeError, ValueError):
            continue

    order_intervals = get_order_intervals(orders)
    chart_data_json = json.dumps(order_intervals)

    if order_times:
        oldest_order_at = min(order_times)
        newest_order_at = max(order_times)

        order_span_seconds = (
            newest_order_at - oldest_order_at
        ).total_seconds() 

        order_span_minutes = order_span_seconds / 60

        if len(order_times) > 1:
            average_seconds_between_orders = (
                order_span_seconds / (len(order_times) - 1)
            )
        else:
            average_seconds_between_orders = None        

        if average_seconds_between_orders is not None:
            average_seconds_display = (
                f"{average_seconds_between_orders:.1f}"
            )
        else:
            average_seconds_display = "N/A"

    if oldest_order_at and newest_order_at:
        oldest_order_iso = oldest_order_at.isoformat()
        newest_order_iso = newest_order_at.isoformat()

        if order_span_minutes.is_integer():
            order_span_display = str(int(order_span_minutes))
        else:
            order_span_display = f"{order_span_minutes:.1f}"
    else:
        oldest_order_iso = ""
        newest_order_iso = ""
        order_span_display = "Unknown"        

    category_map = {
        "ENE": "Drinks",
        "N": "Drinks",
        "REF": "Drinks",
        "RF": "Drinks",
        "BAR": "Ice Cream Bars",
        "BR": "Ice Cream Bars",
        "BAN": "Frozen Bananas",
        "BN": "Frozen Bananas",
        "SHAVE": "Shave Ice",
        "SHV": "Shave Ice",
        "COF": "Coffee",
        "CF": "Coffee",
        "WATER": "Water",
        "WTR": "Water"
    }  

    # Count units ordered by SKU across the displayed orders.
    sku_counts = {}

    # Count units ordered by SKU prefix/category.
    prefix_counts = {}

    orders_json = json.dumps(orders)

    for order in orders:
        items = order.get("items") or []

        for item in items:
            sku = item.get("sku")

            if not sku:
                continue

            quantity = item.get("quantity", 0)

            try:
                quantity = float(quantity)
            except (TypeError, ValueError):
                quantity = 0

            # SKU count
            sku_counts[sku] = (
                sku_counts.get(sku, 0) + quantity
            )

            # Prefix/category count
            if "-" in sku:
                prefix = sku.split("-", 1)[0]
                prefix_counts[prefix] = (
                    prefix_counts.get(prefix, 0) + quantity
                )  
    prefix_rows = []

    for prefix, quantity in sorted(
        prefix_counts.items(),
        key=lambda x: (-x[1], x[0])
    ):
        if quantity.is_integer():
            quantity_display = str(int(quantity))
        else:
            quantity_display = str(quantity)

        prefix_rows.append(
            f"""
            <tr>
                <td>{escape(str(prefix))}</td>
                <td>{quantity_display}</td>
            </tr>
            """
        )

    category_counts = {}

    for prefix, quantity in prefix_counts.items():
        category = category_map.get(prefix, prefix)

        category_counts[category] = (
            category_counts.get(category, 0) + quantity
        )

    category_rows = []

    for category, quantity in sorted(
        category_counts.items(),
        key=lambda x: (-x[1], x[0])
    ):
        if quantity.is_integer():
            quantity_display = str(int(quantity))
        else:
            quantity_display = str(quantity)

        category_rows.append(
            f"""
            <tr>
                <td>{escape(str(category))}</td>
                <td>{quantity_display}</td>
            </tr>
            """
        )

    if category_rows:
        category_html = "\n".join(category_rows)
    else:
        category_html = """
            <tr>
                <td colspan="2">
                    No category data available.
                </td>
            </tr>
        """

    if prefix_rows:
        prefix_html = "\n".join(prefix_rows)
    else:
        prefix_html = """
            <tr>
                <td colspan="2">
                    No category data available.
                </td>
            </tr>
        """
    sku_rows = []

    for sku, quantity in sorted(
        sku_counts.items(),
        key=lambda x: (-x[1], x[0])
    ):
        if quantity.is_integer():
            quantity_display = str(int(quantity))
        else:
            quantity_display = str(quantity)

        sku_rows.append(
            f"""
            <tr>
                <td>{escape(str(sku))}</td>
                <td>{quantity_display}</td>
            </tr>
            """
        )

    if sku_rows:
        sku_html = "\n".join(sku_rows)
    else:
        sku_html = """
            <tr>
                <td colspan="2">
                    No SKU data available.
                </td>
            </tr>
        """
    order_sections = []

    for order in orders:
        order_number = escape(
            str(
                order.get(
                    "orderNumber",
                    order.get("id", "Unknown")
                )
            )
        )

        created_at = escape(
            str(order.get("createdAt", ""))
        )

        # Poynt's statuses object is documented as OrderStatuses.
        # We don't assume a single exact structure here.
        statuses = order.get("statuses") or {}

        status = (
            statuses.get("status")
            if isinstance(statuses, dict)
            else None
        )

        status_display = escape(
            str(status or "Unknown")
        )

        amounts = order.get("amounts") or {}

        total = amounts.get("netTotal")

        if total is None:
            total = amounts.get("orderAmount")

        currency = amounts.get(
            "currency",
            "USD"
        )

        if total is not None:
            try:
                total_display = (
                    f"{escape(str(currency))} "
                    f"${int(total) / 100:.2f}"
                )
            except (TypeError, ValueError):
                total_display = escape(str(total))
        else:
            total_display = "Unknown"

        items = order.get("items") or []

        item_rows = []

        for item in items:
            name = escape(
                str(item.get("name") or "")
            )

            quantity = escape(
                str(item.get("quantity") or "")
            )

            details = escape(
                str(item.get("details") or "")
            )

            sku = escape(
                str(item.get("sku") or "")
            )

            order_notes = escape(
                str(item.get("notes") or "")
            )

            status = escape(
                str(item.get("status") or "")
            )

            item_rows.append(
                f"""
                <tr>
                    <td class="product_name">{name}</td>
                    <td class="product_qty">{quantity}</td>
                    <td class="product_sku">{sku}</td>
                    <td class="order_notes">{order_notes}</td>
                  </tr>
                """
            )

        if item_rows:
            items_html = "\n".join(item_rows)
        else:
            items_html = """
                <tr>
                    <td colspan="3">
                        No order items.
                    </td>
                </tr>
            """

        order_sections.append(
            f"""
            <section class="order">
                <div class="order-header">
                    <div>
                        <strong>Order {order_number}</strong>
                        <span class="status">
                            {status_display}
                        </span>
                    </div>

                    <div>
                        <time
                            class="local-time"
                            datetime="{created_at}"
                        >
                            {created_at}
                        </time>
                    </div>

                    <div>
                        <strong>{total_display}</strong>
                    </div>
                </div>

                <table>
                    <thead>
                        <tr>
                            <th class="product_name">Name</th>
                            <th class="product_qty">Qty</th>
                            <th class="product_sku">SKU</th>
                        </tr>
                    </thead>

                    <tbody>
                        {items_html}
                    </tbody>
                </table>
            </section>
            """
        )

    if order_sections:
        orders_html = "\n".join(order_sections)
    else:
        orders_html = """
            <p>No orders were returned.</p>
        """

    return HTMLResponse(
        f"""
        <!DOCTYPE html>
        <html>
        <head>
            <script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.0/dist/chart.umd.min.js"></script>
            <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>        
            <title>Recent Poynt Orders</title>

            <style>
                body {{
                    font-family: Arial, sans-serif;
                    margin: 30px;
                }}

                h1 {{
                    margin-bottom: 5px;
                }}

                .summary {{
                    margin-bottom: 10px;
                }}

                .order {{
                    margin-bottom: 25px;
                    border: 1px solid #aaa;
                    padding: 12px;
                }}

                .order-header {{
                    display: grid;
                    grid-template-columns: 1fr 1fr auto;
                    gap: 20px;
                    align-items: center;
                    margin-bottom: 10px;
                    font-size: 18px;
                }}

                .status {{
                    margin-left: 10px;
                    font-size: 14px;
                    font-weight: normal;
                }}

                table {{
                    border-collapse: collapse;
                    width: 100%;
                }}

                th,
                td {{
                    border: 1px solid #ccc;
                    padding: 7px;
                    text-align: left;
                    vertical-align: top;
                }}

                th {{
                    font-weight: bold;
                }}
                .sku-summary {{
                    margin-bottom: 30px;
                }}

                .sku-summary table {{
                    width: 400px;
                }}

                .sku-summary th,
                .sku-summary td {{
                    padding: 7px;
                }} 
                .reports {{
                    display: flex;
                    gap: 30px;
                    align-items: flex-start;
                    margin-bottom: 30px;
                }}

                .report {{
                    width: 400px;
                }}

                .report h2 {{
                    margin-bottom: 10px;
                }}  

                .product_name {{ 
                    width: 300px;
                    overflow: hidden;
                    display: inline-block;
                    white-space: nowrap;                
                }}
                .product_qty {{ 
                    width: 50px;
                    overflow: hidden;
                    display: inline-block;
                    white-space: nowrap;                   
                }}
                .product_sku {{ 
                    width: 200px;
                    overflow: hidden;
                    display: inline-block;
                    white-space: nowrap;                   
               
                }}
                .order_notes {{ 
                    width: 300px;
                    overflow: hidden;
                    display: inline-block;
                    white-space: nowrap;                   
               
                }}                

                .chart-container {{
                    width: 100%;
                    margin-bottom: 30px;
                }}

                .chart-container h2 {{
                    margin-bottom: 10px;
                }}

                #orderIntervalChart {{
                    width: 100%;
                    height: 300px;
                }}
               
            </style>
        </head>

        <body>

            <h1>Recent Poynt Orders</h1>

            <p class="summary">
                Showing the most recent
                {len(orders)}
                orders.
            </p>

            <p>
                Orders span:
                <strong>
                    <time
                        class="local-time"
                        datetime="{oldest_order_iso}"
                    >{oldest_order_iso}</time>
                </strong>
                through
                <strong>
                    <time
                        class="local-time"
                        datetime="{newest_order_iso}"
                    >{newest_order_iso}</time>
                </strong>
                |
                <strong>{order_span_display} minutes</strong>
    |
                <strong>{average_seconds_display} sec/order</strong>                

            </p>            

            <p>
                Loaded:
                <time id="page-loaded-time"></time>
            </p>

            <div class="chart-container">
                <h2>Time Between Orders</h2>

                <canvas id="orderIntervalChart"></canvas>
            </div>

            <div class="reports">
                <div class="report">
                    <h2>Items Ordered</h2>

                    <table>
                        <thead>
                            <tr>
                                <th>SKU</th>
                                <th>Units</th>
                            </tr>
                        </thead>

                        <tbody>
                            {sku_html}
                        </tbody>
                    </table>
                </div>

                <div class="report">
                    <h2>Categories</h2>

                    <table>
                        <thead>
                            <tr>
                                <th>Category</th>
                                <th>Units</th>
                            </tr>
                        </thead>

                        <tbody>
                            {category_html}
                        </tbody>
                    </table>
                </div>
            </div>        
            

            {orders_html}

            <p>
                <a href="/dashboard">
                    Return to Dashboard
                </a>
            </p>

            <script>
            
                document
                    .querySelectorAll(".local-time")
                    .forEach(function(element) {{
                        const value =
                            element.getAttribute("datetime");

                        if (!value) {{
                            return;
                        }}

                        const date = new Date(value);

                        if (isNaN(date.getTime())) {{
                            return;
                        }}

                        const formatted =
                            new Intl.DateTimeFormat(
                                undefined,
                                {{
                                    weekday: "long",
                                    month: "long",
                                    day: "numeric",
                                    year: "numeric",
                                    hour: "numeric",
                                    minute: "2-digit",
                                    second: "2-digit",
                                    hour12: true
                                }}
                            ).format(date);

                        element.textContent =
                            formatted.replace(
                                / at /,
                                " | "
                            );
                    }});

                const loadedTime =
                    document.getElementById(
                        "page-loaded-time"
                    );

                if (loadedTime) {{
                    const now = new Date();

                    loadedTime.textContent =
                        new Intl.DateTimeFormat(
                            undefined,
                            {{
                                weekday: "long",
                                month: "long",
                                day: "numeric",
                                year: "numeric",
                                hour: "numeric",
                                minute: "2-digit",
                                second: "2-digit",
                                hour12: true
                            }}
                        ).format(now).replace(
                            / at /,
                            " | "
                        );
                }}
                const orderIntervalData = {chart_data_json};

                const orderIntervalCanvas =
                    document.getElementById("orderIntervalChart");

                if (orderIntervalCanvas && orderIntervalData.length > 0) {{
                    new Chart(orderIntervalCanvas, {{
                        type: "line",

                        data: {{
                            datasets: [{{
                                label: "Seconds Between Orders",

                                data: orderIntervalData.map(function(point) {{
                                    return {{
                                        x: new Date(point.time),
                                        y: point.seconds
                                    }};
                                }}),

                                tension: 0.15,
                                pointRadius: 2,
                                pointHoverRadius: 5,
                                borderWidth: 2,
                                fill: false
                            }}]
                        }},

                        options: {{
                            responsive: true,
                            maintainAspectRatio: false,

                            interaction: {{
                                mode: "nearest",
                                intersect: false
                            }},

                            plugins: {{
                                legend: {{
                                    display: false
                                }},

                                tooltip: {{
                                    callbacks: {{
                                        title: function(context) {{
                                            return new Intl.DateTimeFormat(
                                                undefined,
                                                {{
                                                    weekday: "short",
                                                    month: "short",
                                                    day: "numeric",
                                                    hour: "numeric",
                                                    minute: "2-digit",
                                                    second: "2-digit",
                                                    hour12: true
                                                }}
                                            ).format(context[0].parsed.x);
                                        }},

                                        label: function(context) {{
                                            return context.parsed.y.toFixed(1)
                                                + " seconds since previous order";
                                        }}
                                    }}
                                }}
                            }},

                            scales: {{
                                x: {{
                                    type: "time",

                                    time: {{
                                        tooltipFormat: "MMM d, h:mm:ss a"
                                    }},

                                    title: {{
                                        display: true,
                                        text: "Order Time"
                                    }}
                                }},

                                y: {{
                                    beginAtZero: true,

                                    title: {{
                                        display: true,
                                        text: "Seconds"
                                    }}
                                }}
                            }}
                        }}
                    }});
                }}                
            </script>
            <p>{orders_json}</p>

        </body>
        </html>
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