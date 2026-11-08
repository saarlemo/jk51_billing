"""Email template defaults and validation."""

from pathlib import Path
from string import Template

DEFAULT_NAME = "JK51"
DEFAULT_SUBJECT = "${billing_name} ${report_label} ${identifier}"
SUBJECT_FIELDS = {"billing_name", "report_label", "identifier"}
BODY_FIELDS = {
    "billing_name", "electricity_label", "price_qualifier", "price_missing_sentence",
    "report_type", "period", "weighted_spot_eur_kwh", "total_spot_eur",
    "margin_rate_eur_kwh", "total_margin_eur", "day_kwh", "night_kwh",
    "day_transfer_start", "day_transfer_end", "day_rate_eur_kwh",
    "night_rate_eur_kwh", "day_transfer_eur", "night_transfer_eur", "pmax_rows",
    "fixed_month_count", "monthly_fee_rate", "fixed_total_eur", "monthly_subtotals",
    "total_kwh", "total_eur", "hours_covered", "hours_billed", "hours_excluded",
    "missing_power_hours", "missing_nordpool_hours", "missing_both_hours",
    "missing_power_unit", "missing_nordpool_unit", "missing_both_unit",
}


def validate_template(value, subject=False):
    """Validate template syntax and available placeholders."""
    if not value:
        return
    if subject and ("\n" in value or "\r" in value):
        raise ValueError("Email subject must be a single line")
    template = Template(value)
    if not template.is_valid():
        raise ValueError("Invalid email template placeholder; use ${name} or $$ for a literal dollar sign")
    unknown = set(template.get_identifiers()) - (SUBJECT_FIELDS if subject else BODY_FIELDS)
    if unknown:
        raise ValueError("Unknown email template placeholders: " + ", ".join(sorted(unknown)))


def default_templates():
    """Read the bundled message templates."""
    root = Path(__file__).parent
    return {language: {"subject": DEFAULT_SUBJECT,
                       "body": (root / f"invoice_email-{language}.md").read_text(encoding="utf-8")}
            for language in ("fi", "en")}
