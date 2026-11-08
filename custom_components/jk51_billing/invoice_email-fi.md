# JK51 sähkölasku

Sähkömittarin tietoja ei ollut saatavilla ${missing_power_hours} h ajalta.${price_missing_sentence} Näitä tunteja ei laskuteta.

**Laskutuskausi:** ${period}


## Erittely

| Kustannus | Kulutus | Yksikköhinta | Hinta |
| --- | ---: | ---: | ---: |
| ${electricity_label} | ${total_kwh} kWh | ${weighted_spot_eur_kwh} €/kWh${price_qualifier} | ${total_spot_eur} € |
| Marginaali | ${total_kwh} kWh | ${margin_rate_eur_kwh} €/kWh | ${total_margin_eur} € |
| Päiväsiirto (${day_transfer_start}–${day_transfer_end}) | ${day_kwh} kWh | ${day_rate_eur_kwh} €/kWh | ${day_transfer_eur} € |
| Yösiirto (${day_transfer_end}–${day_transfer_start}) | ${night_kwh} kWh | ${night_rate_eur_kwh} €/kWh | ${night_transfer_eur} € |
${pmax_rows}
| Perusmaksu | ${fixed_month_count} kk | ${monthly_fee_rate} €/kk | ${fixed_total_eur} € |
| **Yhteensä** | | | **${total_eur} €** |

**Kuukausikohtaiset erät:**
${monthly_subtotals}

