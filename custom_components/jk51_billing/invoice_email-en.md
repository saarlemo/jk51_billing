# JK51 electricity invoice

Meter data was unavailable for ${missing_power_hours} ${missing_power_unit}.${price_missing_sentence} These hours are excluded from billing.

**Billing period:** ${period}

## Itemized charges

| Charge | Consumption | Unit price | Amount |
| --- | ---: | ---: | ---: |
| ${electricity_label} | ${total_kwh} kWh | ${weighted_spot_eur_kwh} €/kWh${price_qualifier} | ${total_spot_eur} € |
| Electricity margin | ${total_kwh} kWh | ${margin_rate_eur_kwh} €/kWh | ${total_margin_eur} € |
| Day transfer (07:00–22:00) | ${day_kwh} kWh | ${day_rate_eur_kwh} €/kWh | ${day_transfer_eur} € |
| Night transfer (22:00–07:00) | ${night_kwh} kWh | ${night_rate_eur_kwh} €/kWh | ${night_transfer_eur} € |
${pmax_rows}
| Fixed monthly fee | ${fixed_month_count} months | ${monthly_fee_rate} €/month | ${fixed_total_eur} € |
| **Total** | | | **${total_eur} €** |

**Monthly subtotals:**
${monthly_subtotals}
