# JK51 sähkölasku

Sähkömittarin tietoja ei ollut saatavilla ${missing_power_hours} h ajalta. Pörssisähkön hintoja ei ollut saatavilla ${missing_nordpool_hours} h ajalta. Näitä tunteja ei laskuteta.

**Laskutuskausi:** ${period}


## Erittely

| Kustannus | Kulutus | Yksikköhinta | Hinta |
| --- | ---: | ---: | ---: |
| Pörssisähkö | ${total_kwh} kWh | ${weighted_spot_eur_kwh} €/kWh (painotettu) | ${total_spot_eur} € |
| Marginaali | ${total_kwh} kWh | ${margin_rate_eur_kwh} €/kWh | ${total_margin_eur} € |
| Päiväsiirto (07–22) | ${day_kwh} kWh | ${day_rate_eur_kwh} €/kWh | ${day_transfer_eur} € |
| Yösiirto (22–07) | ${night_kwh} kWh | ${night_rate_eur_kwh} €/kWh | ${night_transfer_eur} € |
${pmax_rows}
| Perusmaksu | ${fixed_month_count} kk | ${monthly_fee_rate} €/kk | ${fixed_total_eur} € |
| **Yhteensä** | | | **${total_eur} €** |

**Kuukausikohtaiset erät:**
${monthly_subtotals}

