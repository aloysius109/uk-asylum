# UK asylum, in detail

A reproducible UK report built from the Home Office asylum summary tables, year ending June 2026. It covers claims, age and nationality, route before claiming, decisions, small boats, inadmissibility, waiting times and backlog, cohorts, children, support and accommodation, and returns. Charts cover nationality, prior route, decisions and outcomes, inadmissibility events, children, UASC grant rates, age assessments, WIP stages and the initial-decision/tribunal caseload comparison. `UASC` means Unaccompanied Asylum-Seeking Child.

The report is intentionally separate from [Asylum Tracker](https://github.com/aloysius109/asylum-tracker), which combines global UNHCR analysis with a shorter UK comparison. This project focuses on the wider Home Office summary tables.

Published report: <https://aloysius109.github.io/uk-asylum/>.

## Source edition

The source workbook is vendored at `data/raw/asylum-summary-jun-2026.ods`. `data/raw/source.json` records its Home Office URL, retrieval time and SHA-256. The analysis verifies that fingerprint and never downloads or replaces the accepted workbook during rendering.

This edition uses the tables listed in `scripts/analyze.py`, plus quarterly extracts from the Home Office claims, pending, returns, migration-transparency and asylum-support workbooks and the Ministry of Justice’s [Tribunal Statistics Quarterly](https://www.gov.uk/government/statistics/tribunals-statistics-quarterly-april-to-june-2026) main tables. The support extract comes from `Data_Asy_D09` in the asylum seekers in receipt of support dataset and includes quarterly accommodation counts by support type and UK region/nation. The queue extract combines the Home Office `ASY_02` and Ministry of Justice `FIA_4` series. `data/raw/quarterly-sources.json` records the workbook URLs and hashes and pins the committed CSV extracts. The workbooks are cached under the ignored `data/raw/cache/` directory; rendering and CI use only the committed CSVs and do not download data.

The ASY_03 work-in-progress queue counts main-applicant cases, not people. Its latest published total is 224,742 cases at June 2024; the report compares its 87,217 cases awaiting an initial decision with D03's 85,839 main-applicant cases at the same date and explains why the two publications are not interchangeable.

ASY_03 is suspended after June 2024, so the current total WIP is not published. Within the separate `ASY_02` initial-decision series, applications awaiting an initial decision fell from 87,217 in June 2024 to 33,514 in June 2026 (61.6%). Meanwhile, MoJ `FIA_4` open cases in the asylum/protection and revocation caseload rose from 33,227 to 90,341; this is a downstream caseload indicator, not a component that can be added to WIP. These sources do not establish whether the total WIP is now larger or smaller than it was in June 2024.

The inadmissibility charts show the Home Office's quarterly events and totals from 2021 Q1 to 2026 Q2. Subsequent admissions and removals are not linked to the people identified in the same table, so their totals are not person-level outcome rates.

The analysis keeps calendar-year, rolling-year and quarterly periods separate, preserves missing or suppressed values as missing, and retains the source’s case/person distinctions. The main initial grant rate is for main applicants: grants of protection or other leave divided by substantive initial decisions (grants plus refusals), excluding withdrawals and administrative outcomes. The small-boat nationality rates are case-based. The 2011 claim totals in `Asy_00a` and `Asy_01a` differ by six and are not artificially reconciled.

The Home Office summary workbook’s own appeals tables (`Asy_06_07`) end in March 2023 and are not included as a report chapter; the separate MoJ `FIA_4` open caseload is used only as a downstream indicator. Prior-route data are Official Statistics in Development. The Home Office says the `Asy_03b` and `Asy_03c` tables will be discontinued after this release.

## Chart conventions

Count axes use comma-separated numbers below 10,000 and `K` abbreviations (with a decimal only when needed) when the axis reaches 10,000 or more. The threshold is defined by `COUNT_AXIS_K_THRESHOLD` in `scripts/analyze.py`; there is no separate chart configuration file. `_quarto.yml` configures the site and its rendering, not chart tick labels.

Chart legends are placed below the plot area so they do not obscure the data. `LEGEND_BORDER_PAD` in `scripts/analyze.py` keeps a clear gap between the legend and the x-axis label; a test checks that the gap is at least 14 points on every chart.

The WIP stage chart keeps the Home Office’s “On Hold” category distinct because it includes cases both before and after an initial decision. The June 2024 “Post Decision” value is shown as an aggregate without a further breakdown; the derived stage series is available in `data/derived/work-in-progress-stages.csv`.

## Rebuild and check

With Python 3.12 and Quarto installed:

```powershell
python -m pip install -r requirements.txt
python scripts/prepare_quarterly.py
python scripts/analyze.py
python scripts/check_report.py
python -m pytest tests
quarto render
```

`prepare_quarterly.py` downloads the six pinned workbooks only when they are not in the local cache, checks their hashes and verifies the extracts against `Asy_00a` and published queue totals. The analysis writes charts to `assets/`, parsed source tables and downloadable CSVs to `data/derived/`, and a dated headline record. Quarto writes the static site to `_site/`.

## Source watch and adopting a new release

Run `python scripts/check_sources.py` to see whether the Home Office data-table page lists a new asylum-summary workbook. The watcher only reads upstream and never changes the report. The weekly workflow reports a change as a GitHub issue; it does not download, adopt or publish a new edition.

To adopt a release, replace the saved workbook and update `data/raw/source.json` only after review. Then rerun `scripts/analyze.py`, revise affected figures and wording in `index.qmd`, run the tests and `scripts/check_report.py`, render and review the site, and re-baseline `sources/watch.json`. A newer source is not published automatically.

## Attribution

Source: UK Home Office, [Immigration system statistics data tables](https://www.gov.uk/government/statistical-data-sets/immigration-system-statistics-data-tables). Reuse is subject to the [Open Government Licence](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).

The report uses GoatCounter in a no-cookie configuration, configured in `analytics.html`.