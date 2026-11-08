# JK51 Electricity Billing for Home Assistant

JK51 Electricity Billing calculates an hourly electricity bill from Home
Assistant recorder statistics. It supports spot and fixed electricity prices, an
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
   or edit settings. It includes an energy sensor selector, electricity pricing, rates,
   language, recipients, Gmail SMTP credentials, and the Home Assistant URL
   and long-lived access token used to retrieve statistics.

Use a Gmail app password rather than your normal Google account password.
Keep credentials private. Rates, price units, VAT treatment, and sensor
statistics must match your contract and recorder configuration. The electricity
price is in €/kWh before the electricity VAT multiplier; set the multiplier to
1 if the price already includes VAT. The electricity margin is added separately.
Fixed-price reports use the configured fixed price for the entire selected
period. Update it when your contract changes and use caution when reporting
historical periods with a different price.

## Email content

Set the billing name under **General settings**. It is used in the default email
subject, message, and attachment filename. Under **Email content**, edit the
subject and Markdown message for the selected language. Finnish and English
have separate templates. Save changes before sending; **Restore default
template** restores the template for the selected language.

Use placeholders such as `${billing_name}`, `${period}`, `${total_kwh}`,
`${total_eur}`, and `${pmax_rows}` in the message. The subject supports
`${billing_name}`, `${report_label}`, and `${identifier}`. Keep the placeholders
for information you want to include; use `$$` for a literal dollar sign. The
attached CSV is generated separately from the message template.

## Actions and scheduling

The integration provides these Home Assistant actions under the
`jk51_billing` domain:

- `jk51_billing.collect` refreshes the recent hourly ledger.
- `jk51_billing.invoice` sends the preceding quarter's invoice on a quarterly
  boundary (January, April, July, or October 1).

Run actions from **Developer tools → Actions**. In the sidebar, **Test billing**
provides month and quarter selectors with buttons to email a report. Save
settings first: test reports use the saved test recipients and CC. Reports
include monthly fixed and peak fees. Test emails are sent only when requested.

The **Billing** section has checkboxes for automatic production invoices at
04:30 in the Home Assistant time zone for the preceding month or quarter. No period is enabled by
default.

**Multiple production periods overlap:** selecting monthly and quarterly, for
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

## Known limitations

- Billing periods with half-hour or quarter-hour UTC offsets are not supported:
  the integration rejects them because its hourly statistics cannot represent
  their boundaries accurately.
- The energy sensor must provide recorded hourly energy changes in kWh. A power
  sensor in W or kW cannot be used directly. Spot pricing also requires a sensor
  with recorded hourly mean prices in €/kWh. Only periods with available
  statistics can be billed.
- Calculations use hourly energy and hourly average spot prices. They do not
  calculate costs at a shorter settlement interval, such as 15 minutes.
- Day and night transfer times use the Home Assistant time zone and must be
  set to whole hours because billing uses hourly statistics. The default day
  period is 07:00–22:00; the night period covers the remaining hours.
- The integration uses the configured rates, transfer times, pricing type,
  VAT multiplier, and margin for the whole report; it does not keep a history of contract
  changes. A report for an earlier period may therefore need different settings.
- The monthly peak is based on available one-hour energy readings. Missing data
  can understate the peak and the resulting fee.
- Email delivery uses Gmail SMTP and requires an app password. Other email
  providers and authentication methods are not supported.
- Missed or failed scheduled sends are not retried automatically. If both
  monthly and quarterly billing are enabled, the invoices overlap.

## Billing cautions

- This is a self-hosted billing aid, not a utility-certified meter or tax
  invoice.
- Missing hourly energy or price data is excluded and reported, never treated
  as zero. Partial-month statistics can understate the peak fee.
- Configure the electricity VAT multiplier for the price and contract.
- The monthly peak fee uses the largest one-hour average, not instantaneous or
  15-minute demand.

