#!/usr/bin/env python3
"""JK51 hourly ledger and billing engine for Home Assistant."""
import asyncio
import csv
import json
import html
import re
import smtplib
import sqlite3
import sys
import threading
from uuid import uuid4
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from email.message import EmailMessage
from pathlib import Path
from string import Template
from zoneinfo import ZoneInfo

import aiohttp

TEMPLATE_ROOT = Path(__file__).resolve().parent
ROOT = TEMPLATE_ROOT
CFG = {}
LOCAL = ZoneInfo("Europe/Helsinki")
UTC = timezone.utc
DB = ROOT / "ledger.sqlite3"
REPORTS = ROOT / "reports"
_ACTION_LOCK = threading.Lock()


def money(value):
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def precise(value):
    return str(value.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP))


def mail_template(filename, values):
    template_path = TEMPLATE_ROOT / filename
    if not template_path.is_file():
        raise RuntimeError(f"Missing email template: {template_path}")
    return Template(template_path.read_text(encoding="utf-8")).substitute(values)


def configured_language():
    """Return the configured email language; omitted language keeps Finnish behavior."""
    language = CFG.get("language", "fi")
    if language not in ("fi", "en"):
        raise RuntimeError("Email language must be 'fi' or 'en'")
    return language


def render_markdown(markdown):
    """Safely render headings, paragraphs, bold and Markdown tables to email HTML."""
    def inline(text):
        return re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", html.escape(text))

    lines = markdown.splitlines()
    output = ["<html><body style='font-family:Arial,sans-serif;color:#222'>"]
    table_open = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                continue
            if not table_open:
                output.append("<table style='border-collapse:collapse;margin:10px 0 18px'>")
                table_open = True
            tag = "th" if output[-1].startswith("<table") else "td"
            output.append("<tr>" + "".join(
                f"<{tag} style='border:1px solid #ddd;padding:7px 10px;text-align:left'>{inline(cell)}</{tag}>"
                for cell in cells) + "</tr>")
            continue
        if table_open:
            output.append("</table>")
            table_open = False
        if not stripped:
            continue
        if stripped.startswith("### "):
            output.append(f"<h3>{inline(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            output.append(f"<h2>{inline(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            output.append(f"<h1>{inline(stripped[2:])}</h1>")
        else:
            output.append(f"<p>{inline(stripped)}</p>")
    if table_open:
        output.append("</table>")
    output.append("</body></html>")
    return "\n".join(output)


def dec(value):
    return Decimal(str(value))


def email_addresses(value, field, required=True):
    """Accept one address or a JSON array; reject unset/empty recipients."""
    if isinstance(value, str):
        addresses = [part.strip() for part in value.split(",")]
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        addresses = [item.strip() for item in value]
    else:
        raise RuntimeError(f"{field} must be an email string or list of strings")
    if any(not address or address == "CHANGE_ME" or "@" not in address
           or "\n" in address or "\r" in address for address in addresses):
        raise RuntimeError(f"Invalid or unconfigured address in {field}")
    if required and not addresses:
        raise RuntimeError(f"Configure {field} before sending")
    return addresses


def require_config(email=False, test_email=False):
    mandatory = ["ha_url", "ha_token", "nordpool_entity", "spot_vat_multiplier",
                 "electricity_margin_eur_per_kwh"]
    if email:
        mandatory += ["recipient", "gmail_user", "gmail_app_password"]
    if test_email:
        mandatory += ["test_recipient", "gmail_user", "gmail_app_password"]
    missing = [k for k in mandatory if CFG.get(k) in (None, "", "CHANGE_ME")]
    if missing:
        raise RuntimeError("Configure the integration first: " + ", ".join(missing))
    if email:
        email_addresses(CFG["recipient"], "recipient")
        email_addresses(CFG.get("cc", []), "cc", required=False)
    if test_email:
        email_addresses(CFG["test_recipient"], "test_recipient")
        email_addresses(CFG.get("test_cc", []), "test_cc", required=False)


def database():
    db = sqlite3.connect(DB)
    db.execute("""CREATE TABLE IF NOT EXISTS hours (
      start_utc TEXT PRIMARY KEY, end_utc TEXT NOT NULL,
      kwh TEXT, spot_eur_kwh TEXT, status TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS sent (
      quarter TEXT PRIMARY KEY, sent_utc TEXT NOT NULL)""")
    db.commit()
    return db


async def statistics(start, end):
    url = CFG["ha_url"].rstrip("/")
    url = url.replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(url, heartbeat=30, timeout=40) as ws:
            hello = await ws.receive_json()
            if hello.get("type") != "auth_required":
                raise RuntimeError(f"Unexpected websocket greeting: {hello}")
            await ws.send_json({"type": "auth", "access_token": CFG["ha_token"]})
            auth = await ws.receive_json()
            if auth.get("type") != "auth_ok":
                raise RuntimeError("Home Assistant authentication failed")
            await ws.send_json({
                "id": 1, "type": "recorder/statistics_during_period",
                "start_time": start.isoformat(), "end_time": end.isoformat(),
                "statistic_ids": [CFG["energy_entity"], CFG["nordpool_entity"]],
                "period": "hour", "types": ["change", "mean"]
            })
            response = await ws.receive_json()
            if not response.get("success"):
                raise RuntimeError("Statistics query failed: " + str(response.get("error")))
            return response["result"]


def key_timestamp(row):
    value = row["start"]
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def rows_for(stats, entity):
    return {key_timestamp(r).isoformat(): r for r in stats.get(entity, [])}


async def collect(start=None, end=None):
    require_config()
    now = datetime.now(UTC)
    end = end or now.replace(minute=0, second=0, microsecond=0)
    # Refresh 72 hours to recover automatically after brief outages.
    start = start or end - timedelta(hours=72)
    values = await statistics(start, end)
    energy = rows_for(values, CFG["energy_entity"])
    prices = rows_for(values, CFG["nordpool_entity"])
    db = database()
    current = start
    counts = {"complete": 0, "missing_energy": 0, "missing_price": 0}
    while current < end:
        key = current.isoformat()
        e = energy.get(key, {}).get("change")
        p = prices.get(key, {}).get("mean")
        if e is None or dec(e) < 0:
            status = "missing_energy"
        elif p is None:
            status = "missing_price"
        else:
            status = "complete"
        counts[status] += 1
        db.execute("""INSERT INTO hours VALUES (?,?,?,?,?)
            ON CONFLICT(start_utc) DO UPDATE SET end_utc=excluded.end_utc,
            kwh=excluded.kwh,spot_eur_kwh=excluded.spot_eur_kwh,status=excluded.status""",
            (key, (current + timedelta(hours=1)).isoformat(),
             str(e) if e is not None else None,
             str(p) if p is not None else None, status))
        current += timedelta(hours=1)
    db.commit()
    db.close()
    print("Collected:", counts)


def previous_quarter():
    today = datetime.now(LOCAL)
    if today.day != 1 or today.month not in (1, 4, 7, 10):
        raise RuntimeError("Invoice only on a quarterly boundary (Jan/Apr/Jul/Oct 1)")
    end = datetime(today.year, today.month, 1, tzinfo=LOCAL)
    month = today.month - 3
    year = today.year
    if month < 1:
        month += 12
        year -= 1
    start = datetime(year, month, 1, tzinfo=LOCAL)
    return start, end


def build_report(start, end, identifier, include_monthly_fees=True, check_sent=True, period_label=None):
    db = database()
    if check_sent and db.execute("SELECT 1 FROM sent WHERE quarter=?", (identifier,)).fetchone():
        raise RuntimeError("This quarter is already marked sent: " + identifier)
    rows = db.execute("SELECT * FROM hours WHERE start_utc >= ? AND start_utc < ? ORDER BY start_utc",
        (start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat())).fetchall()
    expected = int((end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() / 3600)
    by_start = {row[0]: row for row in rows}
    missing_counts = {"missing_energy": 0, "missing_price": 0, "missing_both": 0}
    month_hours = {}
    complete_hours = 0
    day_fee = dec(CFG["day_transfer_eur_per_kwh"])
    night_fee = dec(CFG["night_transfer_eur_per_kwh"])
    peak_fee = dec(CFG["monthly_peak_eur_per_kw"])
    monthly_fee = dec(CFG["monthly_fee_eur"])
    margin_rate = dec(CFG["electricity_margin_eur_per_kwh"])
    vat_factor = dec(CFG["spot_vat_multiplier"])
    totals = {}
    details = []
    current = start.astimezone(UTC)
    stop = end.astimezone(UTC)
    while current < stop:
        start_dt = current
        end_dt = current + timedelta(hours=1)
        start_utc, end_utc = start_dt.isoformat(), end_dt.isoformat()
        row = by_start.get(start_utc)
        kwh, price = (row[2], row[3]) if row else (None, None)
        current = end_dt
        month = start_dt.astimezone(LOCAL).strftime("%Y-%m")
        counts = month_hours.setdefault(month, [0, 0])
        counts[0] += 1
        energy_ok = kwh is not None and dec(kwh).is_finite() and dec(kwh) >= 0
        price_ok = price is not None and dec(price).is_finite()
        if not energy_ok and not price_ok:
            reason = "missing_both"
        elif not energy_ok:
            reason = "missing_energy"
        elif not price_ok:
            reason = "missing_price"
        else:
            reason = "complete"
        local_start = start_dt.astimezone(LOCAL)
        tariff = "night" if local_start.hour >= 22 or local_start.hour < 7 else "day"
        transfer_rate = night_fee if tariff == "night" else day_fee
        if reason != "complete":
            missing_counts[reason] += 1
            details.append([start_utc, end_utc, local_start.isoformat(),
                end_dt.astimezone(LOCAL).isoformat(), "", "", tariff, "", str(transfer_rate),
                "", "", "", reason, str(margin_rate), ""])
            continue
        complete_hours += 1
        counts[1] += 1
        energy = dec(kwh)
        spot = dec(price) * vat_factor
        spot_cost = energy * spot
        margin_cost = energy * margin_rate
        extra_cost = energy * transfer_rate
        # One-hour energy in kWh has the same numerical value as the
        # average power in kW during that one-hour interval.
        hourly_average_kw = energy
        bucket = totals.setdefault(month, [Decimal(0) for _ in range(8)])
        bucket[0] += energy
        bucket[1] += spot_cost
        bucket[2] += extra_cost
        # The margin is assessed on every billable kWh, not on missing hours.
        bucket[3] = max(bucket[3], hourly_average_kw)
        if tariff == "day":
            bucket[4] += energy
            bucket[6] += extra_cost
        else:
            bucket[5] += energy
            bucket[7] += extra_cost
        details.append([start_utc, end_utc,
            local_start.isoformat(), end_dt.astimezone(LOCAL).isoformat(),
            str(energy), str(hourly_average_kw), tariff, str(spot), str(transfer_rate),
            precise(spot_cost), precise(extra_cost), precise(spot_cost + extra_cost + margin_cost),
            "complete", str(margin_rate), precise(margin_cost)])
    if not complete_hours:
        db.close()
        raise RuntimeError(f"No billable hours in {identifier}; email blocked")
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f"JK51_{identifier}_hourly.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["start_utc", "end_utc", "start_local", "end_local", "kwh",
            "average_power_kw", "transfer_tariff", "spot_eur_kwh_incl_vat",
            "transfer_eur_kwh", "spot_cost_eur",
            "extra_cost_eur", "hour_cost_eur", "status",
            "margin_eur_kwh", "margin_cost_eur"])
        writer.writerows(details)
    quarter_kwh = Decimal(0)
    quarter_cost = Decimal(0)
    spot_total = Decimal(0)
    margin_total = Decimal(0)
    day_kwh_total = Decimal(0)
    night_kwh_total = Decimal(0)
    day_transfer_total = Decimal(0)
    night_transfer_total = Decimal(0)
    language = configured_language()
    power_rows = []
    monthly_subtotals = []
    for month in sorted(month_hours):
        kwh, spot, extra, pmax, day_kwh, night_kwh, day_cost, night_cost = (
            totals.get(month, [Decimal(0) for _ in range(8)]))
        fixed = monthly_fee if include_monthly_fees else Decimal(0)
        power_charge = pmax * peak_fee if include_monthly_fees else Decimal(0)
        month_margin = kwh * margin_rate
        subtotal = spot + month_margin + extra + fixed + power_charge
        quarter_kwh += kwh
        quarter_cost += subtotal
        spot_total += spot
        margin_total += month_margin
        day_kwh_total += day_kwh
        night_kwh_total += night_kwh
        day_transfer_total += day_cost
        night_transfer_total += night_cost
        year, month_number = month.split("-")
        power_rows.append(mail_template(f"pmax_row-{language}.md", {
            "month_label": f"{int(month_number)}/{year}",
            "pmax_kw": f"{pmax:.3f}" if month_hours[month][1] else ("ei saatavilla" if language == "fi" else "unavailable"),
            "peak_rate_eur_kw": str(peak_fee),
            "power_eur": money(power_charge),
        }).strip())
        covered, billable = month_hours[month]
        hours_text = "tuntia laskutettu" if language == "fi" else "hours billed"
        monthly_subtotals.append(f"{int(month_number)}/{year}: €{money(subtotal)} "
                                 f"({billable}/{covered} {hours_text})")
    # The fixed fee applies to each calendar month in the billing period, even
    # when its hourly consumption/price data is incomplete.
    fixed_count = len(month_hours) if include_monthly_fees else 0
    missing_total = expected - complete_hours
    body = mail_template(f"invoice_email-{language}.md", {
        "report_type": (("lasku" if include_monthly_fees else "testi (ei perusmaksua)")
                        if language == "fi" else ("invoice" if include_monthly_fees else "test report (no monthly fees)")),
        "period": period_label or f"{start.date()} - {(end - timedelta(days=1)).date()}",
        "weighted_spot_eur_kwh": precise(spot_total / quarter_kwh) if quarter_kwh else "0.00000",
        "total_spot_eur": money(spot_total),
        "margin_rate_eur_kwh": str(margin_rate),
        "total_margin_eur": money(margin_total),
        "day_kwh": f"{day_kwh_total:.3f}",
        "night_kwh": f"{night_kwh_total:.3f}",
        "day_rate_eur_kwh": str(day_fee),
        "night_rate_eur_kwh": str(night_fee),
        "day_transfer_eur": money(day_transfer_total),
        "night_transfer_eur": money(night_transfer_total),
        "pmax_rows": "\n".join(power_rows),
        "fixed_month_count": str(fixed_count),
        "monthly_fee_rate": str(monthly_fee),
        "fixed_total_eur": money(monthly_fee * fixed_count),
        "monthly_subtotals": "\n\n".join(monthly_subtotals),
        "total_kwh": f"{quarter_kwh:.3f}",
        "total_eur": money(quarter_cost),
        "hours_covered": str(expected),
        "hours_billed": str(complete_hours),
        "hours_excluded": str(missing_total),
        "missing_power_hours": str(missing_counts["missing_energy"] + missing_counts["missing_both"]),
        "missing_nordpool_hours": str(missing_counts["missing_price"] + missing_counts["missing_both"]),
        "missing_both_hours": str(missing_counts["missing_both"]),
        "missing_power_unit": "hour" if missing_counts["missing_energy"] + missing_counts["missing_both"] == 1 else "hours",
        "missing_nordpool_unit": "hour" if missing_counts["missing_price"] + missing_counts["missing_both"] == 1 else "hours",
        "missing_both_unit": (("hour" if missing_counts["missing_both"] == 1 else "hours")
                              if language == "en" else ("tunti" if missing_counts["missing_both"] == 1 else "tuntia")),
    })
    return db, identifier, out, body


def send_email(identifier, body, attachment, recipient, is_test=False, subject_identifier=None):
    to_addresses = email_addresses(recipient, "test_recipient" if is_test else "recipient")
    msg = EmailMessage()
    msg["From"] = CFG["gmail_user"]
    msg["To"] = ", ".join(to_addresses)
    cc_field = "test_cc" if is_test else "cc"
    cc_addresses = email_addresses(CFG.get(cc_field, []), cc_field, required=False)
    if cc_addresses:
        msg["Cc"] = ", ".join(cc_addresses)
    subject_identifier = subject_identifier or identifier
    if configured_language() == "en":
        msg["Subject"] = f"JK51 test report {subject_identifier}" if is_test else f"JK51 electricity invoice {subject_identifier}"
    else:
        msg["Subject"] = f"JK51 testilasku {subject_identifier}" if is_test else f"JK51 sähkölasku {subject_identifier}"
    msg.set_content(body)
    msg.add_alternative(render_markdown(body), subtype="html")
    msg.add_attachment(attachment.read_bytes(), maintype="text", subtype="csv",
                       filename=attachment.name)
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=40) as smtp:
        smtp.starttls()
        smtp.login(CFG["gmail_user"], CFG["gmail_app_password"])
        smtp.send_message(msg)


async def invoice():
    require_config(email=True)
    start, end = previous_quarter()
    # Refresh the billing period; missing hours are excluded from the report.
    await collect(start.astimezone(UTC), end.astimezone(UTC))
    ident = f"{start.year}-Q{(start.month - 1)//3 + 1}"
    db, ident, csv_path, body = build_report(start, end, ident)
    (REPORTS / f"JK51_{ident}_summary.txt").write_text(body, encoding="utf-8")
    try:
        send_email(ident, body, csv_path, CFG["recipient"])
        db.execute("INSERT INTO sent VALUES (?,?)", (ident, datetime.now(UTC).isoformat()))
        db.commit()
    finally:
        db.close()
    print(f"Sent {ident} to {CFG['recipient']}, cc {CFG.get('cc', [])}")


async def test_day():
    """Generate yesterday's report and email it only to test_recipient."""
    require_config(test_email=True)
    today = datetime.now(LOCAL).date()
    end = datetime(today.year, today.month, today.day, tzinfo=LOCAL)
    start = end - timedelta(days=1)
    await collect(start.astimezone(UTC), end.astimezone(UTC))
    ident = start.strftime("TEST-%Y-%m-%d")
    db, _, csv_path, body = build_report(
        start, end, ident, include_monthly_fees=False, check_sent=False)
    summary = REPORTS / f"JK51_{ident}_summary.txt"
    summary.write_text(body, encoding="utf-8")
    db.close()
    send_email(ident, body, csv_path, CFG["test_recipient"], is_test=True)
    print(body)
    print(f"Daily test sent to {CFG['test_recipient']}; files: {summary} and {csv_path}")



def previous_period(period, today=None):
    """Return the last complete local calendar period and a stable invoice ID."""
    today = today or datetime.now(LOCAL).date()
    end = datetime(today.year, today.month, today.day, tzinfo=LOCAL)
    if period == "daily":
        start = end - timedelta(days=1)
        identifier = start.strftime("%Y-%m-%d")
    elif period == "weekly":
        if today.weekday() != 0:
            raise RuntimeError("Weekly billing runs on Monday")
        start = end - timedelta(days=7)
        iso = start.isocalendar()
        identifier = f"{iso.year}-W{iso.week:02d}"
    elif period == "monthly":
        if today.day != 1:
            raise RuntimeError("Monthly billing runs on the first day of the month")
        year, month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        start = datetime(year, month, 1, tzinfo=LOCAL)
        identifier = start.strftime("%Y-%m")
    elif period == "quarterly":
        if today.day != 1 or today.month not in (1, 4, 7, 10):
            raise RuntimeError("Quarterly billing runs on a quarter boundary")
        month = today.month - 3
        year = today.year
        if month < 1:
            month += 12
            year -= 1
        start = datetime(year, month, 1, tzinfo=LOCAL)
        identifier = f"{year}-Q{(month - 1) // 3 + 1}"
    else:
        raise ValueError("Unknown billing period")
    return start, end, identifier


async def scheduled_report(period, is_test):
    """Collect, render and send one completed period, once per recipient group."""
    require_config(test_email=is_test, email=not is_test)
    start, end, identifier = previous_period(period)
    if is_test:
        identifier = f"TEST-{period.upper()}-{identifier}"
    # Check before the expensive refresh, then check again while building the report.
    db = database()
    try:
        if db.execute("SELECT 1 FROM sent WHERE quarter=?", (identifier,)).fetchone():
            return
    finally:
        db.close()
    await collect(start.astimezone(UTC), end.astimezone(UTC))
    db, _, csv_path, body = build_report(
        start, end, identifier, include_monthly_fees=period in ("monthly", "quarterly"))
    try:
        if period in ("daily", "weekly"):
            note = ("Monthly fixed and peak fees are not included in this report."
                    if configured_language() == "en" else
                    "Kuukausittaista perus- ja tehomaksua ei sisällytetä tähän raporttiin.")
            body += "\n\n" + note + "\n"
        (REPORTS / f"JK51_{identifier}_summary.txt").write_text(body, encoding="utf-8")
        send_email(identifier, body, csv_path,
                   CFG["test_recipient"] if is_test else CFG["recipient"], is_test=is_test)
        db.execute("INSERT INTO sent VALUES (?,?)", (identifier, datetime.now(UTC).isoformat()))
        db.commit()
    finally:
        db.close()


def parse_test_period(period, value, now=None):
    """Convert a selected completed Helsinki calendar period to UTC boundaries."""
    try:
        if period == "daily" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            first = date.fromisoformat(value)
            last = first + timedelta(days=1)
        elif period == "weekly" and (match := re.fullmatch(r"(\d{4})-W(\d{2})", value)):
            first = date.fromisocalendar(int(match[1]), int(match[2]), 1)
            last = first + timedelta(days=7)
        elif period == "monthly" and (match := re.fullmatch(r"(\d{4})-(\d{2})", value)):
            first = date(int(match[1]), int(match[2]), 1)
            last = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
        elif period == "quarterly" and (match := re.fullmatch(r"(\d{4})-Q([1-4])", value)):
            year, quarter = int(match[1]), int(match[2])
            first = date(year, 3 * quarter - 2, 1)
            last = date(year + (quarter == 4), (3 * quarter) % 12 + 1, 1)
        else:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Choose a valid day, week, month or quarter") from None
    now = now or datetime.now(UTC)
    if last > now.astimezone(LOCAL).date():
        raise ValueError("Choose a completed period")
    start = datetime(first.year, first.month, first.day, tzinfo=LOCAL)
    end = datetime(last.year, last.month, last.day, tzinfo=LOCAL)
    return start.astimezone(UTC), end.astimezone(UTC)


async def manual_test_report(period, value):
    """Send a selected completed period without changing sent records."""
    start, end = parse_test_period(period, value)
    require_config(test_email=True)
    await collect(start, end)
    identifier = f"TEST-MANUAL-{period.upper()}-{uuid4().hex}"
    first = start.astimezone(LOCAL).date()
    last = end.astimezone(LOCAL).date() - timedelta(days=1)
    db, _, csv_path, body = build_report(start, end, identifier,
        include_monthly_fees=period in ("monthly", "quarterly"),
        check_sent=False, period_label=f"{first} – {last}")
    try:
        if period in ("daily", "weekly"):
            note = ("Monthly fixed and peak fees are not included in this report."
                    if configured_language() == "en" else
                    "Kuukausittaista perus- ja tehomaksua ei sisällytetä tähän raporttiin.")
            body += "\n\n" + note + "\n"
        (REPORTS / f"JK51_{identifier}_summary.txt").write_text(body, encoding="utf-8")
        send_email(identifier, body, csv_path, CFG["test_recipient"], is_test=True,
                   subject_identifier=value)
    finally:
        db.close()


def _run_action_sync(config, action, data_dir, start=None, end=None):
    """Run one serialized billing action in an executor thread."""
    global CFG, ROOT, DB, REPORTS
    with _ACTION_LOCK:
        old = CFG, ROOT, DB, REPORTS
        try:
            CFG = dict(config)
            ROOT = Path(data_dir).expanduser().resolve()
            ROOT.mkdir(parents=True, exist_ok=True)
            DB = ROOT / "ledger.sqlite3"
            REPORTS = ROOT / "reports"
            if action == "collect":
                asyncio.run(collect())
            elif action == "test_day":
                asyncio.run(test_day())
            elif action == "manual_test":
                asyncio.run(manual_test_report(start, end))
            elif action == "invoice":
                asyncio.run(invoice())
            elif action.startswith("scheduled_billing_"):
                asyncio.run(scheduled_report(action.removeprefix("scheduled_billing_"), False))
            else:
                raise RuntimeError(f"Unknown JK51 billing action: {action}")
        finally:
            CFG, ROOT, DB, REPORTS = old


async def async_run_action(hass, config, action, data_dir, start=None, end=None):
    """Execute a billing action off Home Assistant's event loop.

    Args:
        hass: Home Assistant instance, used for its executor.
        config: Mapping containing the configured billing options.
        action: Billing action to run.
        data_dir: Directory for the ledger database and generated reports.
    """
    await hass.async_add_executor_job(_run_action_sync, config, action, data_dir, start, end)
