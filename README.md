# JK51 Electricity Billing for Home Assistant

JK51 Electricity Billing calculates an hourly electricity bill from Home
Assistant recorder statistics. It accounts for Nord Pool spot prices, an
additional electricity margin, day/night transfer rates, fixed monthly fees,
and the highest one-hour average power fee. It includes Finnish and English
email templates.

## Install manually

1. Copy the complete `custom_components/jk51_billing/` directory into your
   Home Assistant configuration directory at
   `custom_components/jk51_billing/`. Keep its frontend, templates, and JSON
   files in place.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration**, search for
   **JK51 Electricity Billing**, and complete its setup form.
4. Open the **Electricity billing** administrator-only sidebar panel to review
   or edit settings. It includes energy and Nord Pool sensor selectors, rates,
   language, recipients, Gmail SMTP credentials, and the Home Assistant URL
   and long-lived access token used to retrieve statistics.

Use a Gmail app password rather than your normal Google account password.
Keep credentials private. Rates, spot price units, VAT treatment, and sensor
statistics must match your contract and recorder configuration.

## Actions and scheduling

The integration provides these Home Assistant actions under the
`jk51_billing` domain:

- `jk51_billing.collect` refreshes the recent hourly ledger.
- `jk51_billing.test_day` emails yesterday's report to the test recipients and CC.
- `jk51_billing.invoice` sends the preceding quarter's invoice on a quarterly
  boundary (January, April, July, or October 1).

Run actions from **Developer tools → Actions**. In the sidebar, **Test billing**
provides a day, ISO week (Monday–Sunday), month and quarter selector, each with
a button to email a report for that completed Helsinki calendar period. Save
settings first: test reports use the saved test recipients and CC. Daily and
weekly reports omit monthly fixed and peak fees; monthly and quarterly reports
include them. Test emails are sent only when requested; the integration does
not schedule them automatically.

The **Billing** section has checkboxes for automatic production invoices at
04:30 Helsinki time for the preceding complete period. No period is enabled by
default. The same monthly-fee rules apply.

**Multiple production periods overlap:** selecting daily and monthly, for
example, sends separate invoices for some of the same consumption. Select
periods carefully to avoid charging twice. The integration records successful
sends for each period in its ledger, but cannot guarantee exactly-once delivery
if it stops after SMTP accepts an email and before the ledger is updated.
Schedules missed while Home Assistant is down, and failed sends, are not
retried automatically; inspect the logs and sent mail. Disable any old
periodic invoice automations when using the panel schedules. Disable any old
test-email automations if you want test emails only on demand.
The optional `integration_automations.example.yaml` includes alternatives for
manual Home Assistant automations; do not enable duplicate schedules.

## Persistent data and upgrades

The integration stores its SQLite ledger and reports in
`/config/jk51_billing/`. Back up this directory, including `ledger.sqlite3`:
the ledger records sent invoices and prevents the same period from being sent
again. If migrating an existing ledger, back it up and place it in this
directory before sending invoices. Configuration is managed through the
integration setup and sidebar panel.

## Billing cautions

- This is a self-hosted billing aid, not a utility-certified meter or tax
  invoice.
- Missing hourly energy or price data is excluded and reported, never treated
  as zero. Partial-month statistics can understate the peak fee.
- Configure the spot price VAT multiplier for the actual sensor and contract.
- The monthly peak fee uses the largest one-hour average, not instantaneous or
  15-minute demand.
- The calculations use the Europe/Helsinki time zone and historical Home
  Assistant statistics.

