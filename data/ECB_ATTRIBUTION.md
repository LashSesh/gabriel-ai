# ECB reference-rate observations

Source: ECB statistics, European Central Bank.

- Original source: https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip
- Retrieved: 26 September 2026.
- Original ZIP: `ecb_eurofxref-hist_20260926.zip` (unchanged bytes).
- Extracted source CSV: `ecb_eurofxref-hist_20260926.csv` (unchanged bytes).
- CSV SHA-256: `e8136f072d575cb891cb58718fe31602ca2d4feccee67f035106393ed1c4bdbb`.
- 7,101 source rows, 4 January 1999 through 25 September 2026.
- Source units: foreign-currency units per euro.

The ECB reference rates are published for information purposes. They are not
executable quotes. The ECB normally updates them around 16:00 CET on its working
days. This archive is a current revised snapshot; it does not supply historical
receipt times or the complete sequence of earlier vintages.

Metadata and methodology:
https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html

Reuse is governed by the ECB's own terms, including attribution and accurate
reproduction of source observations and metadata:
https://www.ecb.europa.eu/stats/ecb_statistics/governance_and_quality_framework/html/usage_policy.en.html
https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html

These files are not assigned the manuscript's or code's license. No ECB
endorsement or independently verified historical availability is implied.

The project's arrays in `results/ecb_risk_predictions.npz`, its log losses,
variance states, empirical risk forecasts and summary statistics are **Gabriel
calculations based on ECB statistics**, not statistics published by the ECB.
The original CSV remains unchanged. The code sorts dates and selects USD, GBP,
JPY and CHF, all complete and positive in this source. No imputation is applied.
The development and evaluation windows, target-endpoint restrictions, units and
model choices are specified in `results/ecb_risk_protocol.json`.
