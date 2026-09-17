from sku_map import fix_sku
from categories import sku_prefix_to_category_map
import json
from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from datetime import datetime, timedelta
from urllib.parse import urlencode
from poynt.token import exchange_authorization_code
from zoneinfo import ZoneInfo
from devices import icc_stores

from poynt.client import (
    PoyntClient,
    PoyntReauthorizationRequired,
)

from dotenv import load_dotenv
import os
from database import SessionLocal
from models import Employee, OrganizationMember
from tip_submission_model import TipSubmission
from poynt.connection import get_poynt_connection, get_poynt_credentials
from organization_context import get_current_organization_id
from permissions import (
    get_organization_role,
    role_can_manage_integrations,
    role_can_view_payroll_reports,
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


@router.get("/settings/integrations/poynt", response_class=HTMLResponse)
async def poynt_settings(request: Request):
    user_id = request.session.get("user_id")

    if not user_id:
        return RedirectResponse("/login", status_code=303)

    organization_id = get_current_organization_id(request)
    if organization_id is None:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    role = get_organization_role(user_id, organization_id)
    if not role_can_manage_integrations(role):
        return templates.TemplateResponse(
            request=request,
            name="message.html",
            context={
                "title": "Poynt Access Denied",
                "paragraphs": [
                    "Only organization owners and managers can manage the Poynt connection."
                ],
                "show_dashboard_link": True,
            },
            status_code=403,
        )

    connection = get_poynt_connection(organization_id)

    return templates.TemplateResponse(
        request=request,
        name="poynt_settings.html",
        context={
            "organization_role": role,
            "poynt_connection": connection,
        },
    )


@router.get("/poynt/catalog", response_class=HTMLResponse)
async def poynt_catalog(request: Request):

    user_id = request.session.get("user_id")

    if not user_id:
        return RedirectResponse(
            "/login",
            status_code=303
        )

    organization_id = get_current_organization_id(request)

    if organization_id is None:
        request.session.clear()
        return RedirectResponse(
            "/login",
            status_code=303
        )

    credentials = get_poynt_credentials(organization_id)

    if not credentials:
        return templates.TemplateResponse(
            request=request,
            name="message.html",
            context={
                "title": "Poynt Error",
                "paragraphs": [
                    "No Poynt connection was found."
                ],
                "show_dashboard_link": True,
            },
            status_code=404,
        )

    try:
        client = PoyntClient(
            credentials,
            organization_id=organization_id,
        )


        catalogs = await client.get_catalogs()

    except PoyntReauthorizationRequired:
        return templates.TemplateResponse(
            request=request,
            name="message.html",
            context={
                "title": "Poynt Authorization Required",
                "paragraphs": [
                    "Your Poynt authorization has expired.",
                    "Please reconnect your Poynt account.",
                ],
                "show_dashboard_link": True,
            },
            status_code=401,
        )

    except Exception as e:
        print(
            f"Poynt catalog request failed: "
            f"{type(e).__name__}: {e}",
            flush=True
        )

        return templates.TemplateResponse(
            request=request,
            name="message.html",
            context={
                "title": "Poynt Catalog Error",
                "paragraphs": [
                    "The catalog request failed.",
                    "Check the application logs.",
                ],
                "show_dashboard_link": True,
            },
            status_code=502,
        )

    return templates.TemplateResponse(
        request=request,
        name="message.html",
        context={
            "title": "Poynt Catalog Success!",
            "paragraphs": [
                "Catalog request succeeded.",
                "The Poynt access token was retrieved from the database and used to make this request.",
            ],
            "show_dashboard_link": True,
        },
    )

def  get_prefix_counts(orders, sku_counts):   # Count units ordered by SKU prefix/category.
    prefix_counts = {}

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

    return prefix_counts            


def format_duration(seconds):
    """
    Convert a duration in seconds into a human-friendly
    value + unit string.
    """

    if seconds is None:
        return "-"

    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "-"

    if seconds < 60:
        value = round(seconds)
        unit = "second" if value == 1 else "seconds"

    elif seconds < 3600:
        value = round(seconds / 60, 1)

        # Remove unnecessary .0
        if value.is_integer():
            value = int(value)

        unit = "minute" if value == 1 else "minutes"

    elif seconds < 86400:
        value = round(seconds / 3600, 1)

        if value.is_integer():
            value = int(value)

        unit = "hour" if value == 1 else "hours"

    else:
        value = round(seconds / 86400, 1)

        if value.is_integer():
            value = int(value)

        unit = "day" if value == 1 else "days"

    return f"{value} {unit}"

def get_fastest_processing_times(orders):
    """
    Estimate best cashier processing pace by order complexity.

    For each order-complexity group:
      1 item
      2 items
      3 items

    Use the fastest 10% of valid order intervals, capped at 10
    intervals, and return the median of those intervals.

    The interval is attributed to the newer order.
    """

    chronological_orders = sorted(
        orders,
        key=lambda order: order.get("createdAt", "")
    )

    intervals_by_size = {
        "1": [],
        "2": [],
        "3": [],
    }

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

        # We need a previous order to establish an interval.
        if previous_time is not None:
            interval_seconds = (
                current_time - previous_time
            ).total_seconds()

            # Count total units in this order.
            total_items = 0

            for item in order.get("items") or []:
                quantity = item.get("quantity", 0)

                try:
                    total_items += float(quantity)
                except (TypeError, ValueError):
                    continue

            if total_items == 1:
                group = "1"
            elif total_items == 2:
                group = "2"
            elif total_items == 3:
                group = "3"
            else:
                group = None

            if group is not None and interval_seconds >= 0:
                intervals_by_size[group].append(
                    interval_seconds
                )

        previous_time = current_time

    results = {}

    for group, intervals in intervals_by_size.items():

        if not intervals:
            results[group] = None
            continue

        # Fastest 10%, capped at 10 intervals.
        sample_size = min(
            10,
            max(1, (len(intervals) + 9) // 10)
        )

        fastest_intervals = sorted(intervals)[:sample_size]

        # Median without requiring another import.
        middle = len(fastest_intervals) // 2

        if len(fastest_intervals) % 2:
            median_seconds = fastest_intervals[middle]
        else:
            median_seconds = (
                fastest_intervals[middle - 1]
                + fastest_intervals[middle]
            ) / 2

        results[group] = median_seconds

    return results

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
    

def get_item_flow(orders):
    chronological_orders = list(reversed(orders))

    item_flow = {}

    first_bucket = None
    last_bucket = None

    for order in chronological_orders:
        created_at = order.get("createdAt")

        if not created_at:
            continue

        try:
            order_time = datetime.fromisoformat(
                created_at.replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            continue

        bucket_minute = (order_time.minute // 5) * 5

        bucket_time = order_time.replace(
            minute=bucket_minute,
            second=0,
            microsecond=0
        )

        if first_bucket is None:
            first_bucket = bucket_time

        last_bucket = bucket_time

        total_items = 0

        for item in order.get("items") or []:
            quantity = item.get("quantity", 0)

            try:
                total_items += float(quantity)
            except (TypeError, ValueError):
                continue

        item_flow[bucket_time] = (
            item_flow.get(bucket_time, 0) + total_items
        )

    if first_bucket is None:
        return []

    # Fill every five-minute bucket, including zero-activity buckets.
    result = []

    bucket_time = first_bucket

    while bucket_time <= last_bucket:
        result.append({
            "time": bucket_time.isoformat(),
            "items": item_flow.get(bucket_time, 0),
        })

        bucket_time += timedelta(minutes=5)

    return result

def get_available_store_ids(orders):
    """
    Get the store IDs found in the original order collection.
    """

    store_ids = set()

    for order in orders:
        for transaction in order.get("transactions") or []:
            context = transaction.get("context") or {}
            store_id = context.get("storeId")

            if store_id:
                store_ids.add(store_id.lower())

    return sorted(
        store_ids,
        key=lambda store_id: icc_stores.get(
            store_id,
            f"Unknown Store {store_id}",
        ).lower(),
    )


def filter_orders_by_stores(orders, stores):
    """
    Filter orders to those associated with the requested stores.

    If stores is None or empty, return all orders.
    """

    logger.info("filtering stores to: %s", stores)

    if not stores:
        return orders

    requested_stores = {
        store.lower()
        for store in stores
        if store
    }

    if not requested_stores:
        return orders

    filtered_orders = []

    for order in orders:
        for transaction in order.get("transactions") or []:
            context = transaction.get("context") or {}
            store_id = context.get("storeId")

            if store_id and store_id.lower() in requested_stores:
                filtered_orders.append(order)
                break

    logger.info(
        "store filtering reduced %s orders to %s orders",
        len(orders),
        len(filtered_orders),
    )

    return filtered_orders

def get_revenue_flow(orders):
    chronological_orders = list(reversed(orders))

    revenue_flow = {}
    first_bucket = None
    last_bucket = None

    for order in chronological_orders:
        created_at = order.get("createdAt")

        if not created_at:
            continue

        try:
            order_time = datetime.fromisoformat(
                created_at.replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            continue

        bucket_minute = (order_time.minute // 5) * 5

        bucket_time = order_time.replace(
            minute=bucket_minute,
            second=0,
            microsecond=0
        )

        if first_bucket is None:
            first_bucket = bucket_time

        last_bucket = bucket_time

        amounts = order.get("amounts") or {}

        total = amounts.get("netTotal")

        if total is None:
            total = amounts.get("orderAmount")

        try:
            revenue = float(total) / 100
        except (TypeError, ValueError):
            revenue = 0

        revenue_flow[bucket_time] = (
            revenue_flow.get(bucket_time, 0) + revenue
        )

    if first_bucket is None:
        return []

    # Fill every five-minute bucket, including zero-activity buckets.
    result = []

    bucket_time = first_bucket

    while bucket_time <= last_bucket:
        result.append({
            "time": bucket_time.isoformat(),
            "revenue": round(
                revenue_flow.get(bucket_time, 0),
                2
            ),
        })

        bucket_time += timedelta(minutes=5)

    return result

def get_sku_rows(sku_counts):
    """Prepare SKU count data for template rendering."""
    sku_rows = []

    for sku, quantity in sorted(
        sku_counts.items(),
        key=lambda x: (-x[1], x[0])
    ):
        if quantity.is_integer():
            quantity_display = str(int(quantity))
        else:
            quantity_display = str(quantity)

        sku_rows.append({
            "sku": fix_sku(str(sku)),
            "quantity": quantity_display,
        })

    return sku_rows


def get_category_rows(category_map, prefix_counts):
    """Prepare category count data for template rendering."""
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

        category_rows.append({
            "category": str(category),
            "quantity": quantity_display,
        })

    return category_rows

def validate_and_convert_iso_datetime(iso_string: str):
    if iso_string == "":
        return None

    try:
        return datetime.fromisoformat(iso_string)

    except ValueError:
        logger.warning(
            "date/time parameter %s was not a valid ISO datetime string",
            iso_string
        )
        return None


def get_orders_date_range(start, end):
    start_at_date = validate_and_convert_iso_datetime(start)
    end_at_date = validate_and_convert_iso_datetime(end)

    arizona_tz = ZoneInfo("America/Phoenix")

    if start_at_date and start_at_date.tzinfo is None:
        start_at_date = start_at_date.replace(
            tzinfo=arizona_tz
        )

    if end_at_date and end_at_date.tzinfo is None:
        end_at_date = end_at_date.replace(
            tzinfo=arizona_tz
        )

    if not start:
        return {
            "error_title": "Start Date Required",
            "error_message": "A start date and time are required.",
        }

    if not end:
        return {
            "error_title": "End Date Required",
            "error_message": "An end date and time are required.",
        }

    if not start_at_date:
        return {
            "error_title": "Start Date Error",
            "error_message": "The start date and time are not valid.",
        }

    if not end_at_date:
        return {
            "error_title": "End Date Error",
            "error_message": "The end date and time are not valid.",
        }

    if end_at_date < start_at_date:
        return {
            "error_title": "Date Range Error",
            "error_message": "The end date and time must be after the start date and time.",
        }

    max_span = timedelta(days=3)

    if end_at_date - start_at_date > max_span:
        return {
            "error_title": "Date Range Too Long",
            "error_message": "The order report can cover a maximum of 3 days.",
        }


    span_seconds = end_at_date - start_at_date if start_at_date and end_at_date else None

    if span_seconds:
        span_seconds = span_seconds.total_seconds()
    
    return {
        "start_at": start_at_date.isoformat(),
        "end_at": end_at_date.isoformat(),
        "span_seconds": span_seconds,
    }


async def fetch_poynt_orders(
    credentials,
    organization_id,
    start_at,
    end_at,
):
    client = PoyntClient(
        credentials,
        organization_id=organization_id,
    )

    return await client.get_recent_orders(
        100,
        start_at=start_at,
        end_at=end_at,
        fetch_all=True,
    )


def filter_completed_orders(orders):
    completed_orders = []
    cancelled_order_count = 0

    for order in orders:
        statuses = order.get("statuses") or {}

        transaction_status = statuses.get(
            "transactionStatusSummary"
        )

        if transaction_status == "COMPLETED":
            completed_orders.append(order)
        else:
            cancelled_order_count += 1

    return completed_orders, cancelled_order_count


def calculate_order_metrics(orders):
    """
    Calculate the core metrics for a collection of completed orders.

    Returns raw numeric values and datetime objects.
    Formatting for display happens elsewhere.
    """

    total_revenue = 0.0
    total_items = 0.0
    total_tips = 0.0
    order_times = []

    for order in orders:
        amounts = order.get("amounts") or {}

        # Revenue
        total = amounts.get("netTotal")

        if total is None:
            total = amounts.get("orderAmount")

        try:
            total_revenue += float(total) / 100
        except (TypeError, ValueError):
            pass

        # Tips
        captured_totals = amounts.get("capturedTotals")

        if captured_totals:
            tip = captured_totals.get("tipAmount")
        else:
            tip = 0

        try:
            total_tips += float(tip) / 100
        except (TypeError, ValueError):
            pass

        # Items
        for item in order.get("items") or []:
            quantity = item.get("quantity", 0)

            try:
                total_items += float(quantity)
            except (TypeError, ValueError):
                pass

        # Order timestamp
        created_at = order.get("createdAt")

        if created_at:
            try:
                order_time = datetime.fromisoformat(
                    created_at.replace("Z", "+00:00")
                )
                order_times.append(order_time)
            except (TypeError, ValueError):
                logger.warning(
                    "missing created at for order: %s",
                    order
                )

    oldest_order_at = None
    newest_order_at = None
    order_span_seconds = None
    average_seconds_between_orders = None
    average_seconds_between_items = None
    items_per_order = None
    tip_ratio = None

    if order_times:
        oldest_order_at = min(order_times)
        newest_order_at = max(order_times)

        order_span_seconds = (
            newest_order_at - oldest_order_at
        ).total_seconds()

        if len(order_times) > 1:
            average_seconds_between_orders = (
                order_span_seconds / (len(order_times) - 1)
            )

        if total_items > 1:
            average_seconds_between_items = (
                order_span_seconds / (total_items - 1)
            )

    if orders:
        items_per_order = total_items / len(orders)

    if total_revenue:
        tip_ratio = total_tips / total_revenue

    return {
        "total_revenue": total_revenue,
        "total_items": total_items,
        "total_tips": total_tips,
        "oldest_order_at": oldest_order_at,
        "newest_order_at": newest_order_at,
        "order_span_seconds": order_span_seconds,
        "average_seconds_between_orders": average_seconds_between_orders,
        "average_seconds_between_items": average_seconds_between_items,
        "items_per_order": items_per_order,
        "tip_ratio": tip_ratio,
    }

def prepare_chart_data(orders):
    """
    Prepare chart data for the orders report.

    Returns raw chart data and JSON strings for use by JavaScript.
    """

    order_intervals = get_order_intervals(orders)
    item_flow = get_item_flow(orders)
    revenue_flow = get_revenue_flow(orders)

    return {
        "order_intervals": order_intervals,
        "order_intervals_json": json.dumps(order_intervals),
        "item_flow": item_flow,
        "item_flow_json": json.dumps(item_flow),
        "revenue_flow": revenue_flow,
        "revenue_flow_json": json.dumps(revenue_flow),
    }


def get_orders_data(orders):
    """
    Prepare order data for the orders report.

    Returns:
        orders_data: list of dictionaries containing order display data
        store_ids: set of store IDs found in the orders
    """

    orders_data = []
    store_ids = set()

    for order in orders:

        order_number = str(
            order.get(
                "orderNumber",
                order.get("id", "Unknown")
            )
        )

        transactions = order.get("transactions") or []

        for transaction in transactions:
            context = transaction.get("context") or {}
            store_id = context.get("storeId")

            if store_id:
                store_ids.add(store_id)

        created_at = str(
            order.get("createdAt", "")
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
                    f"{currency} "
                    f"${int(total) / 100:.2f}"
                )
            except (TypeError, ValueError):
                total_display = str(total)
        else:
            total_display = "Unknown"

        notes = str(
            order.get("notes") or ""
        )

        items_data = []

        for item in order.get("items") or []:

            name = str(
                item.get("name") or ""
            )

            quantity = str(
                item.get("quantity") or ""
            )

            sku = str(
                item.get("sku") or ""
            )

            sku = fix_sku(sku)

            item_status = str(
                item.get("status") or ""
            )

            items_data.append({
                "name": name,
                "quantity": quantity,
                "sku": sku,
                "status": item_status,
            })

        orders_data.append({
            "order_number": order_number,
            "created_at": created_at,
            "total_display": total_display,
            "notes": notes,
            "items": items_data,
        })

    return orders_data, store_ids



def get_tip_calculator_data(orders):
    """
    Prepare the minimal order data needed by the in-browser
    tip calculator.

    Returns:
        list of dictionaries containing:
        - created_at: order timestamp
        - tip_cents: captured tip amount in cents
    """

    tip_data = []

    for order in orders:
        created_at = order.get("createdAt")

        if not created_at:
            continue

        amounts = order.get("amounts") or {}
        captured_totals = amounts.get("capturedTotals") or {}

        tip = captured_totals.get("tipAmount", 0)

        try:
            tip_cents = int(tip)
        except (TypeError, ValueError):
            tip_cents = 0

        tip_data.append({
            "created_at": created_at,
            "tip_cents": tip_cents,
        })

    return tip_data


def get_tip_calculator_employees(organization_id: int) -> list[dict]:
    """Return active employees available for tip allocation."""
    with SessionLocal() as session:
        employees = session.execute(
            select(Employee)
            .where(
                Employee.organization_id == organization_id,
                Employee.is_active.is_(True),
            )
            .order_by(Employee.last_name, Employee.first_name)
        ).scalars().all()

    return [
        {
            "id": employee.id,
            "name": f"{employee.first_name} {employee.last_name}",
        }
        for employee in employees
    ]

def get_stores_display(store_ids):
    """
    Convert a set of store IDs into display text.

    Returns a human-readable string containing the
    names of all stores found in the orders.
    """

    stores_display = ""
    first = True

    for store_id in store_ids:
        logger.debug("Store id %s found", store_id)

        if not first:
            stores_display += " + "

        if store_id.lower() not in icc_stores:
            stores_display = f"Unknown Store {store_id}"
            logger.warning("Unknown Store %s", store_id)
        else:
            stores_display += icc_stores[store_id.lower()]

        first = False

    return stores_display



def _parse_tip_submission_datetime(value: str) -> datetime:
    """Parse an ISO timestamp and normalize it to a naive UTC datetime."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    return parsed


def _get_today_utc_bounds() -> tuple[datetime, datetime]:
    """Return today's Phoenix calendar day as naive UTC database bounds."""
    phoenix = ZoneInfo("America/Phoenix")
    utc = ZoneInfo("UTC")
    today = datetime.now(phoenix).date()
    start_local = datetime.combine(today, datetime.min.time(), tzinfo=phoenix)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(utc).replace(tzinfo=None),
        end_local.astimezone(utc).replace(tzinfo=None),
    )


def _get_tip_report_date_bounds(start_date: str, end_date: str) -> tuple[datetime, datetime, str, str] | None:
    """Convert inclusive Phoenix calendar dates into UTC database bounds."""
    try:
        start = datetime.fromisoformat(start_date).date()
        end = datetime.fromisoformat(end_date).date()
    except (TypeError, ValueError):
        return None

    if end < start:
        return None

    phoenix = ZoneInfo("America/Phoenix")
    utc = ZoneInfo("UTC")

    start_local = datetime.combine(start, datetime.min.time(), tzinfo=phoenix)
    end_local = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=phoenix)

    return (
        start_local.astimezone(utc).replace(tzinfo=None),
        end_local.astimezone(utc).replace(tzinfo=None),
        start.isoformat(),
        end.isoformat(),
    )


def _aggregate_tip_allocations(ranges: list) -> list[dict]:
    """Sum each employee's per-range allocation across a submission."""
    totals: dict[str, dict] = {}

    for tip_range in ranges:
        if not isinstance(tip_range, dict):
            continue

        employees = tip_range.get("employees") or []
        if not isinstance(employees, list) or not employees:
            continue

        try:
            raw_per_employee_cents = tip_range.get("per_employee_cents")
            if raw_per_employee_cents is None:
                raise ValueError
            per_employee_cents = int(raw_per_employee_cents)
        except (TypeError, ValueError):
            try:
                total_tip_cents = int(tip_range.get("total_tip_cents", 0))
            except (TypeError, ValueError):
                total_tip_cents = 0
            per_employee_cents = total_tip_cents // len(employees)

        for employee in employees:
            if not isinstance(employee, dict):
                continue

            employee_id = employee.get("id")
            employee_name = employee.get("name") or "Unknown Employee"
            key = (
                f"id:{employee_id}"
                if employee_id is not None
                else f"name:{employee_name.casefold()}"
            )

            if key not in totals:
                totals[key] = {
                    "id": employee_id,
                    "name": employee_name,
                    "total_tip_cents": 0,
                }

            totals[key]["total_tip_cents"] += max(0, per_employee_cents)

    return list(totals.values())


def _tip_submission_display(submission: TipSubmission) -> dict:
    try:
        data = json.loads(submission.submission_data)
    except (TypeError, ValueError):
        data = {}

    ranges = data.get("ranges", [])
    if not isinstance(ranges, list):
        ranges = []

    return {
        "id": submission.id,
        "store_name": submission.store_name,
        "report_start_at": submission.report_start_at.isoformat(),
        "report_end_at": submission.report_end_at.isoformat(),
        "total_tip_cents": submission.total_tip_cents,
        "payout_method": submission.payout_method,
        "submitted_at": submission.submitted_at.isoformat(),
        "ranges": ranges,
        "employee_totals": _aggregate_tip_allocations(ranges),
        "employee_names": [
            employee.get("name", "Unknown Employee")
            for tip_range in ranges
            if isinstance(tip_range, dict)
            for employee in (tip_range.get("employees") or [])
            if isinstance(employee, dict)
        ],
    }


@router.get("/poynt/tip-submissions", response_class=HTMLResponse)
async def tip_submission_report(
    request: Request,
    start: str = "",
    end: str = "",
    payment: str = "",
):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    organization_id = get_current_organization_id(request)
    if organization_id is None:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    # Date-range access is controlled server-side. The disabled inputs on the
    # employee view are only a UI convenience and are not an authorization check.
    role = get_organization_role(user_id, organization_id)
    can_select_date_range = role_can_view_payroll_reports(role)

    phoenix = ZoneInfo("America/Phoenix")
    today = datetime.now(phoenix).date().isoformat()

    if can_select_date_range:
        # Privileged users get a selectable inclusive date range. Default to today.
        start_date = start or today
        end_date = end or today
        bounds = _get_tip_report_date_bounds(start_date, end_date)
        if bounds is None:
            start_date = today
            end_date = today
            bounds = _get_tip_report_date_bounds(start_date, end_date)
            validation_message = "The selected date range was invalid, so today's submissions are shown."
        else:
            validation_message = ""
    else:
        # Everyone else can only see today's submissions, regardless of URL parameters.
        start_date = today
        end_date = today
        bounds = _get_tip_report_date_bounds(start_date, end_date)
        validation_message = ""

    day_start, day_end, _, _ = bounds

    selected_payment = payment if payment in {"cash", "paycheck"} else ""

    submission_query = select(TipSubmission).where(
        TipSubmission.organization_id == organization_id,
        TipSubmission.submitted_at >= day_start,
        TipSubmission.submitted_at < day_end,
    )

    if selected_payment:
        submission_query = submission_query.where(
            TipSubmission.payout_method == selected_payment
        )

    submission_query = submission_query.order_by(
        TipSubmission.submitted_at.desc(),
        TipSubmission.id.desc(),
    )

    with SessionLocal() as session:
        submissions = session.execute(submission_query).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="tip_submissions.html",
        context={
            "submissions": [_tip_submission_display(item) for item in submissions],
            "tip_report_start_date": start_date,
            "tip_report_end_date": end_date,
            "tip_report_can_select_date_range": can_select_date_range,
            "tip_report_validation_message": validation_message,
            "tip_report_payment": selected_payment,
        },
    )


@router.post("/poynt/tip-submissions")
async def submit_tip_record(
    request: Request,
    store_id: str = Form(...),
    store_name: str = Form(...),
    report_start_at: str = Form(...),
    report_end_at: str = Form(...),
    total_tip_cents: int = Form(...),
    payout_method: str = Form(...),
    submission_json: str = Form(...),
):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    organization_id = get_current_organization_id(request)
    if organization_id is None:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    if payout_method not in {"cash", "paycheck"}:
        return RedirectResponse("/poynt/orders", status_code=303)

    try:
        report_start = _parse_tip_submission_datetime(report_start_at)
        report_end = _parse_tip_submission_datetime(report_end_at)
        submission_data = json.loads(submission_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return RedirectResponse("/poynt/orders", status_code=303)

    if report_start >= report_end:
        return RedirectResponse("/poynt/orders", status_code=303)

    if not isinstance(submission_data, dict) or not isinstance(
        submission_data.get("ranges"), list
    ) or not submission_data.get("ranges"):
        return RedirectResponse("/poynt/orders", status_code=303)

    if len(submission_data["ranges"]) > 6:
        return RedirectResponse("/poynt/orders", status_code=303)

    for tip_range in submission_data["ranges"]:
        if not isinstance(tip_range, dict):
            return RedirectResponse("/poynt/orders", status_code=303)
        if not isinstance(tip_range.get("employees"), list) or not tip_range["employees"]:
            return RedirectResponse("/poynt/orders", status_code=303)

    with SessionLocal() as session:
        submission = TipSubmission(
            organization_id=organization_id,
            submitted_by_user_id=user_id,
            store_id=store_id,
            store_name=store_name,
            report_start_at=report_start,
            report_end_at=report_end,
            total_tip_cents=max(0, int(total_tip_cents)),
            payout_method=payout_method,
            submission_data=json.dumps(submission_data),
        )
        session.add(submission)
        session.commit()

    return RedirectResponse("/poynt/tip-submissions", status_code=303)

@router.get("/poynt/orders", response_class=HTMLResponse)
async def poynt_orders(
    request: Request,
    start: str = "",
    end: str = "",
    stores: list[str] | None = Query(default=None),    
):
    user_id = request.session.get("user_id")
    logger.info("filtering stores to: %s", stores)


    if not user_id:
        return RedirectResponse(
            "/login",
            status_code=303
        )

    organization_id = get_current_organization_id(request)

    if organization_id is None:
        request.session.clear()
        return RedirectResponse(
            "/login",
            status_code=303
        )

    if not start and not end:
        return templates.TemplateResponse(
            request=request,
            name="orders.html",
            context={
                "report_generated": False,
                "validation_title": "",
                "validation_message": "Enter a start and end date and time to generate order metrics.",
                "start_input_value": "",
                "end_input_value": "",
                "chart_data_json": "[]",
                "item_flow_json": "[]",
                "revenue_flow_json": "[]",

                # Tip Calculator defaults
                "tip_calculator_data": [],
                "tip_calculator_enabled": False,
                "tip_calculator_store_name": "",
                "tip_calculator_store_id": "",
                "start_at_for_tip_calculator": None,
                "end_at_for_tip_calculator": None,
            },
        )
    order_date_params = get_orders_date_range(start, end)

    if "error_title" in order_date_params:
        return templates.TemplateResponse(
            request=request,
            name="orders.html",
            context={
                "report_generated": False,
                "validation_title": order_date_params["error_title"],
                "validation_message": order_date_params["error_message"],
                "start_input_value": start,
                "end_input_value": end,
                "chart_data_json": "[]",
                "item_flow_json": "[]",
                "revenue_flow_json": "[]",
            },
        )

    start_at = order_date_params['start_at']
    end_at = order_date_params['end_at']
    report_span_seconds = order_date_params['span_seconds'] 

    # preserve inputs    
    start_input_value = start
    end_input_value = end    

    credentials = get_poynt_credentials(organization_id)

    logger.info(
        "Poynt orders credentials: found=%s",
        credentials is not None,
    )       

    if not credentials:
        return templates.TemplateResponse(
            request=request,
            name="message.html",
            context={
                "title": "Poynt Error",
                "paragraphs": [
                    "No Poynt connection was found."
                ],
                "show_dashboard_link": True,
            },
            status_code=404,
        )

    try:
        orders = await fetch_poynt_orders(
            credentials,
            organization_id,
            start_at,
            end_at,
        )

        if not orders:
            logger.info(
                "No Poynt orders found for requested date range: %s - %s",
                start_at,
                end_at,
            )

            return templates.TemplateResponse(
                request=request,
                name="orders.html",
                context={
                    "report_generated": False,
                    "validation_title": "No Orders Found",
                    "validation_message": (
                        "No orders were found for the selected date range."
                    ),
                    "start_input_value": start,
                    "end_input_value": end,
                    "available_stores": [],
                    "selected_stores": [],
                    "chart_data_json": "[]",
                    "item_flow_json": "[]",
                    "revenue_flow_json": "[]",

                    # Tip Calculator defaults
                    "tip_calculator_data": [],
                    "tip_calculator_enabled": False,
                    "tip_calculator_store_name": "",
                    "start_at_for_tip_calculator": None,
                    "end_at_for_tip_calculator": None,
                },
            )
        
        available_store_ids = get_available_store_ids(orders)

        if not available_store_ids:
            return templates.TemplateResponse(
                request=request,
                name="orders.html",
                context={
                    "report_generated": False,
                    "validation_title": "No Store Data",
                    "validation_message": "No store information was found in the orders for this date range.",
                    "start_input_value": start,
                    "end_input_value": end,
                    "available_stores": [],
                    "selected_stores": [],
                    "chart_data_json": "[]",
                    "item_flow_json": "[]",
                    "revenue_flow_json": "[]",
                },
            )

        available_store_set = set(available_store_ids)

        if stores:
            requested_stores = {
                store.lower()
                for store in stores
                if store
            }
            selected_store_ids = sorted(
                requested_stores & available_store_set
            )

            if not selected_store_ids:
                selected_store_ids = available_store_ids
        else:
            selected_store_ids = available_store_ids

        orders = filter_orders_by_stores(
            orders,
            selected_store_ids if stores else None,
        )

    except PoyntReauthorizationRequired:
        return templates.TemplateResponse(
            request=request,
            name="message.html",
            context={
                "title": "Poynt Authorization Required",
                "paragraphs": [
                    "Your Poynt authorization has expired.",
                    "Please reconnect your Poynt account.",
                ],
                "show_dashboard_link": True,
            },
            status_code=401,
        )

    except Exception as e:
        logger.error(
            "Poynt recent orders request failed: %s",
            e,
        )

        return templates.TemplateResponse(
            request=request,
            name="message.html",
            context={
                "title": "Poynt Orders Error",
                "paragraphs": [
                    "The recent orders request failed.",
                    "Check the application logs.",
                ],
                "show_dashboard_link": True,
            },
            status_code=502,
        )


    summary_text = f"{len(orders)}"

    # Newest first.
    orders = sorted(
        orders,
        key=lambda order: order.get("createdAt", ""),
        reverse=True,
    )

    orders, cancelled_order_count = filter_completed_orders(orders)                

    metrics = calculate_order_metrics(orders)

    total_revenue = metrics["total_revenue"]
    total_items = metrics["total_items"]
    total_tips = metrics["total_tips"]

    oldest_order_at = metrics["oldest_order_at"]
    newest_order_at = metrics["newest_order_at"]

    order_span_seconds = metrics["order_span_seconds"]
    average_seconds_between_orders = metrics[
        "average_seconds_between_orders"
    ]
    average_seconds_between_items = metrics[
        "average_seconds_between_items"
    ]

    items_per_order = metrics["items_per_order"]
    tip_ratio = metrics["tip_ratio"]

    chart_data = prepare_chart_data(orders)

    chart_data_json = chart_data["order_intervals_json"]
    item_flow_json = chart_data["item_flow_json"]
    revenue_flow_json = chart_data["revenue_flow_json"]

    fastest_processing = get_fastest_processing_times(orders)

    if total_items.is_integer():
        total_items_display = str(int(total_items))
    else:
        total_items_display = str(total_items)
    # END Insert

    if isinstance(items_per_order, float):
        items_per_order_display = f"{items_per_order:,.2f}"
    else:
        logger.debug("items_per_order %s isn't a float", items_per_order)    
        items_per_order_display = "-"

    if isinstance(tip_ratio, float):    
        tip_ratio_display = f"{tip_ratio:,.1%}"
    else:
        logger.debug(" %s isn't a float", tip_ratio)    
        tip_ratio_display = "-"        

    total_revenue_display = f"${total_revenue:,.2f}"
    total_tips_display = f"${total_tips:,.2f}"
    revenue_per_hour_orders = total_revenue / (order_span_seconds / 3600) if order_span_seconds else 0
    revenue_per_hour_orders_display = f"${revenue_per_hour_orders:,.2f}"  
    revenue_per_hour_range = total_revenue / (report_span_seconds / 3600) if order_span_seconds else 0
    revenue_per_hour_report_display = f"${revenue_per_hour_range:,.2f}"  
    cog_ratio = 0.25
    tax_rate_estimate = 0.083
    profit_rate_per_hour = revenue_per_hour_range * (1 - cog_ratio - tax_rate_estimate)
    profit_per_hour_display = f"${profit_rate_per_hour:,.2f}"   

    fastest_1_item = fastest_processing.get("1")
    fastest_2_item = fastest_processing.get("2")
    fastest_3_item = fastest_processing.get("3")

    fastest_1_item_display = (
        f"{fastest_1_item:.1f}"
        if fastest_1_item is not None
        else "-"
    )

    fastest_2_item_display = (
        f"{fastest_2_item:.1f}"
        if fastest_2_item is not None
        else "-"
    )

    fastest_3_item_display = (
        f"{fastest_3_item:.1f}"
        if fastest_3_item is not None
        else "-"
    )    

    chart_display_flag = ""
    if not len(orders):
        chart_display_flag = "display: none;"    

    if order_span_seconds is not None:
        order_span_time_duration_display = format_duration(
            order_span_seconds
        )
    else:
        order_span_time_duration_display = "-"

    if average_seconds_between_items is not None:
        average_seconds_between_items_display = (
            f"{average_seconds_between_items:.1f}"
        )
    else:
        average_seconds_between_items_display = "-"

    if average_seconds_between_orders is not None:
        average_seconds_display = (
            f"{average_seconds_between_orders:.1f}"
        )
    else:
        average_seconds_display = "-"    

    if oldest_order_at and newest_order_at:
        oldest_order_iso = oldest_order_at.isoformat()
        newest_order_iso = newest_order_at.isoformat()

    else:
        oldest_order_iso = ""
        newest_order_iso = ""
        order_span_display = "Unknown"        

    # Count units ordered by SKU across the displayed orders.
    sku_counts = {}

    prefix_counts = get_prefix_counts(orders, sku_counts)

    sku_rows = get_sku_rows(sku_counts)

    category_rows = get_category_rows(
        sku_prefix_to_category_map,
        prefix_counts,
    )

    orders_data, store_ids = get_orders_data(orders)    

    stores_display = get_stores_display(store_ids)

    tip_calculator_data = get_tip_calculator_data(orders)

    tip_calculator_employees = get_tip_calculator_employees(
        organization_id
    )

    tip_calculator_enabled = (
        len(store_ids) == 1
        and bool(tip_calculator_employees)
    )

    tip_calculator_store_name = (
        stores_display
        if len(store_ids) == 1
        else ""
    )

    if len(store_ids) != 1:
        tip_calculator_disabled_reason = (
            "Tip Calculator requires exactly one store in the report."
        )
    elif not tip_calculator_employees:
        tip_calculator_disabled_reason = (
            "Add an active employee before using the Tip Calculator."
        )
    else:
        tip_calculator_disabled_reason = ""

    available_stores = [
        {
            "id": store_id,
            "name": icc_stores.get(
                store_id,
                f"Unknown Store {store_id}",
            ),
        }
        for store_id in available_store_ids
    ]

    return templates.TemplateResponse(
        request=request,
        name="orders.html",
        context={
            "report_generated": True,
            "summary_text": summary_text,
            "cancelled_order_count": cancelled_order_count,
            "total_revenue_display": total_revenue_display,
            "total_revenue": total_revenue,
            "total_items_display": total_items_display,
            "items_per_order_display": items_per_order_display,
            "total_tips_display": total_tips_display,
            "tip_ratio_display": tip_ratio_display,
            "average_seconds_display": average_seconds_display,
            "average_seconds_between_items_display": average_seconds_between_items_display,
            "fastest_1_item_display": fastest_1_item_display,
            "fastest_2_item_display": fastest_2_item_display,
            "fastest_3_item_display": fastest_3_item_display,
            "chart_display_flag": chart_display_flag,
            "oldest_order_iso": oldest_order_iso,
            "newest_order_iso": newest_order_iso,
            "order_span_time_duration_display": order_span_time_duration_display,
            "start_input_value": start_input_value,
            "end_input_value": end_input_value,
            "stores_display": stores_display,
            "available_stores": available_stores,
            "selected_stores": selected_store_ids,
            "sku_rows": sku_rows,
            "category_rows": category_rows,
            "orders_data": orders_data,
            "chart_data_json": chart_data_json,
            "item_flow_json": item_flow_json,
            "revenue_flow_json": revenue_flow_json,
            "revenue_per_hour_orders_display": revenue_per_hour_orders_display,
            "revenue_per_hour_report_display": revenue_per_hour_report_display,
            "profit_per_hour_display": profit_per_hour_display,
            "tip_calculator_data": tip_calculator_data,
            "tip_calculator_employees": tip_calculator_employees,
            "tip_calculator_enabled": tip_calculator_enabled,
            "tip_calculator_store_name": tip_calculator_store_name,
            "tip_calculator_store_id": next(iter(store_ids), "") if len(store_ids) == 1 else "",
            "tip_calculator_disabled_reason": tip_calculator_disabled_reason,
            "start_at_for_tip_calculator": start_at,
            "end_at_for_tip_calculator": end_at,                  
        },
    )



@router.get("/poynt/stores", response_class=HTMLResponse)
async def poynt_stores(
    request: Request,
    start: str = "",
    end: str = "",
):
    user_id = request.session.get("user_id")

    if not user_id:
        return RedirectResponse(
            "/login",
            status_code=303
        )

    organization_id = get_current_organization_id(request)

    if organization_id is None:
        request.session.clear()
        return RedirectResponse(
            "/login",
            status_code=303
        )

    credentials = get_poynt_credentials(organization_id)

    if not credentials:
        return templates.TemplateResponse(
            request=request,
            name="message.html",
            context={
                "title": "Poynt Error",
                "paragraphs": [
                    "No Poynt connection was found."
                ],
                "show_dashboard_link": True,
            },
            status_code=404,
        )

    try:
        client = PoyntClient(
            credentials,
            organization_id=organization_id,
        )

        businesses = await client.get_stores()

    except PoyntReauthorizationRequired:
        return templates.TemplateResponse(
            request=request,
            name="message.html",
            context={
                "title": "Poynt Authorization Required",
                "paragraphs": [
                    "Your Poynt authorization has expired.",
                    "Please reconnect your Poynt account.",
                ],
                "show_dashboard_link": True,
            },
            status_code=401,
        )

    except Exception as e:
        print(
            f"Poynt stores request failed: "
            f"{type(e).__name__}: {e}",
            flush=True
        )

        return templates.TemplateResponse(
            request=request,
            name="message.html",
            context={
                "title": "Poynt stores Error",
                "paragraphs": [
                    "The stores request failed.",
                    "Check the application logs.",
                ],
                "show_dashboard_link": True,
            },
            status_code=502,
        )

    return templates.TemplateResponse(
        request=request,
        name="message.html",
        context={
            "title": "Poynt Stores Success!",
            "paragraphs": [
                "Stores request succeeded.",
                "The Poynt access token was retrieved from the database and used to make this request.",
            ],
            "show_dashboard_link": True,
        },
    )
    
