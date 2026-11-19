"""Prepare pinned quarterly asylum flows, return, work-in-progress and queue data."""
import argparse
import hashlib
import json
import re
import shutil
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyze import load_tables, value_for  # noqa: E402

CACHE = ROOT / "data" / "raw" / "cache"
QUARTERLY_PATH = ROOT / "data" / "raw" / "quarterly-extract.csv"
WORK_IN_PROGRESS_PATH = ROOT / "data" / "raw" / "asylum-work-in-progress.csv"
SUPPORT_PATH = ROOT / "data" / "raw" / "support-accommodation-extract.csv"
QUEUE_INDICATORS_PATH = ROOT / "data" / "raw" / "queue-indicators.csv"
MANIFEST_PATH = ROOT / "data" / "raw" / "quarterly-sources.json"
SOURCE_PAGE = "https://www.gov.uk/government/statistical-data-sets/immigration-system-statistics-data-tables"
TRANSPARENCY_PAGE = "https://www.gov.uk/government/statistical-data-sets/migration-transparency-data"
TRIBUNAL_PAGE = "https://www.gov.uk/government/statistics/tribunals-statistics-quarterly-april-to-june-2026"
SOURCES = {
    "claims_decisions": {
        "url": (
            "https://assets.publishing.service.gov.uk/media/6a85c2d7c9205b515d421eeb/"
            "asylum-claims-datasets-jun-2026.xlsx"
        ),
        "filename": "asylum-claims-datasets-jun-2026.xlsx",
    },
    "pending": {
        "url": (
            "https://assets.publishing.service.gov.uk/media/6a85c2bcb0504df9f2c897ff/"
            "asylum-claims-awaiting-decision-datasets-jun-2026.xlsx"
        ),
        "filename": "asylum-claims-awaiting-decision-datasets-jun-2026.xlsx",
    },
    "returns": {
        "url": (
            "https://assets.publishing.service.gov.uk/media/6a85c4f754bcee010d514572/"
            "returns-datasets-jun-2026.xlsx"
        ),
        "filename": "returns-datasets-jun-2026.xlsx",
    },
    "transparency": {
        "url": (
            "https://assets.publishing.service.gov.uk/media/6a96a66b3b22fb169dc18fe4/"
            "immigration-and-protection-data-apr-to-jun-2026.xlsx"
        ),
        "filename": "immigration-and-protection-data-apr-to-jun-2026.xlsx",
    },
    "support": {
        "url": (
            "https://assets.publishing.service.gov.uk/media/6a85c2f1c9205b515d421eec/"
            "asylum-seekers-receipt-support-datasets-jun-2026.xlsx"
        ),
        "filename": "asylum-seekers-receipt-support-datasets-jun-2026.xlsx",
    },
    "tribunals": {
        "url": (
            "https://assets.publishing.service.gov.uk/media/6aa18eb1c5796a7a179c658d/"
            "Tribunals_Statistics_Quarterly_Main_Tables_Q1_2026_27.ods"
        ),
        "filename": "Tribunals_Statistics_Quarterly_Main_Tables_Q1_2026_27.ods",
    },
}
QUARTERLY_COLUMNS = [
    "quarter", "period_end", "claims", "grants", "refusals", "substantive_decisions",
    "withdrawals", "admin_outcomes", "enforced_returns", "voluntary_returns",
    "refused_entry_returns", "asylum_related_returns", "people_awaiting_initial_decision",
    "main_applicants_awaiting_initial_decision",
]
OUTCOME_GROUPS = {
    "grants": ("Grant of Protection", "Grant of Other Leave"),
    "refusals": ("Refused",),
    "withdrawals": ("Withdrawn",),
    "admin_outcomes": ("Administrative Outcome",),
}
RETURN_TYPES = {
    "enforced_returns": "Enforced return",
    "voluntary_returns": "Voluntary return",
    "refused_entry_returns": "Refused entry at port and subsequently departed",
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def get_workbook(name, source, expected_hash=None):
    path = CACHE / source["filename"]
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".part")
        request = urllib.request.Request(source["url"], headers={"User-Agent": "uk-asylum-report/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            temporary.replace(path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    actual_hash = sha256(path)
    if expected_hash and actual_hash != expected_hash:
        raise ValueError(f"Pinned {name} workbook SHA-256 changed; review the new source before adopting it.")
    return path, actual_hash


def quarter_range():
    result = []
    for year in range(2010, 2027):
        for quarter in range(1, 5):
            if year == 2026 and quarter > 2:
                break
            result.append(f"{year} Q{quarter}")
    return result


def quarter_end(quarter):
    year, quarter_number = quarter.split(" Q")
    month = int(quarter_number) * 3
    return f"{year}-{month:02d}-{pd.Period(f'{year}-{month:02d}', freq='M').days_in_month:02d}"


def count_value(value):
    if pd.isna(value):
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", ":", "-", "z", "..", "n/a", "na"}:
        return None
    number = pd.to_numeric(text, errors="raise")
    if float(number).is_integer():
        return int(number)
    raise ValueError(f"Expected a whole-number count; found {value!r}.")


def sum_by_quarter(data, value_column):
    return data.groupby("Quarter", dropna=True)[value_column].sum().to_dict()


def parse_quarterly_sources(paths):
    claims_data = pd.read_excel(paths["claims_decisions"], sheet_name="Data_Asy_D01", header=1, engine="openpyxl")
    decisions_data = pd.read_excel(paths["claims_decisions"], sheet_name="Data_Asy_D02", header=1, engine="openpyxl")
    pending_data = pd.read_excel(paths["pending"], sheet_name="Data_Asy_D03", header=1, engine="openpyxl")
    returns_data = pd.read_excel(paths["returns"], sheet_name="Data_Ret_D05", header=1, engine="openpyxl")

    required = {
        "claims": (claims_data, {"Quarter", "Claims"}),
        "decisions": (decisions_data, {"Quarter", "Case outcome group", "Decisions"}),
        "pending": (pending_data, {"Date (as at...)", "Application stage", "Applicant type", "Claims"}),
        "returns": (returns_data, {"Quarter", "Return type group", "Number of asylum-related returns"}),
    }
    for name, (data, columns) in required.items():
        if not columns.issubset(data.columns):
            raise ValueError(f"The {name} workbook table is missing expected fields: {sorted(columns - set(data.columns))}.")

    quarters = quarter_range()
    claims = sum_by_quarter(claims_data, "Claims")
    decision_totals = decisions_data.groupby(["Quarter", "Case outcome group"], dropna=True)["Decisions"].sum()
    returns_totals = returns_data.groupby(["Quarter", "Return type group"], dropna=True)[
        "Number of asylum-related returns"
    ].sum()

    pending_dates = pd.to_datetime(pending_data["Date (as at...)"], errors="coerce", dayfirst=True)
    if pending_dates.isna().any():
        raise ValueError("The pending-stock workbook contains an unrecognised snapshot date.")
    pending_data = pending_data.copy()
    pending_data["Quarter"] = (
        pending_dates.dt.year.astype(str) + " Q" + pending_dates.dt.quarter.astype(str)
    )
    pending_data = pending_data.loc[pending_data["Application stage"] == "Pending initial decision"]
    pending = sum_by_quarter(pending_data, "Claims")
    pending_main_applicants = sum_by_quarter(
        pending_data.loc[pending_data["Applicant type"] == "Main Applicant"], "Claims"
    )

    rows = []
    for quarter in quarters:
        outcomes = {name: 0 for name in OUTCOME_GROUPS}
        for key, groups in OUTCOME_GROUPS.items():
            outcomes[key] = sum(
                int(decision_totals.get((quarter, group), 0))
                for group in groups
            )
        return_values = {
            key: int(returns_totals.get((quarter, label), 0))
            for key, label in RETURN_TYPES.items()
        }
        grants = outcomes["grants"]
        refusals = outcomes["refusals"]
        rows.append({
            "quarter": quarter,
            "period_end": quarter_end(quarter),
            "claims": int(claims.get(quarter, 0)),
            "grants": grants,
            "refusals": refusals,
            "substantive_decisions": grants + refusals,
            "withdrawals": outcomes["withdrawals"],
            "admin_outcomes": outcomes["admin_outcomes"],
            **return_values,
            "asylum_related_returns": return_values["enforced_returns"] + return_values["voluntary_returns"],
            "people_awaiting_initial_decision": pending.get(quarter),
            "main_applicants_awaiting_initial_decision": pending_main_applicants.get(quarter),
        })
    quarterly = pd.DataFrame(rows, columns=QUARTERLY_COLUMNS)
    for column in ("people_awaiting_initial_decision", "main_applicants_awaiting_initial_decision"):
        quarterly[column] = pd.array(quarterly[column], dtype="Int64")
    return quarterly


def parse_support_sources(path):
    data = pd.read_excel(path, sheet_name="Data_Asy_D09", header=1, engine="openpyxl")
    required = {"Nationality", "Region", "Support Type", "Accommodation Type", "UK Region / Nation", "People"}
    if not required.issubset(data.columns) or len(data.columns) < 7:
        raise ValueError(f"The support workbook table is missing expected fields: {sorted(required - set(data.columns))}.")

    dates = pd.to_datetime(data.iloc[:, 0], errors="coerce", dayfirst=True)
    if dates.isna().any() or not dates.dt.is_quarter_end.all():
        raise ValueError("The support workbook contains an unrecognised or non-quarter-end snapshot date.")
    people = pd.to_numeric(data["People"], errors="coerce")
    if people.isna().any() or (people < 0).any() or not people.mod(1).eq(0).all():
        raise ValueError("The support workbook contains a missing, negative or non-integer people count.")

    prepared = data[["Support Type", "Accommodation Type", "UK Region / Nation"]].copy()
    prepared["quarter"] = dates.dt.year.astype(str) + " Q" + dates.dt.quarter.astype(str)
    prepared["period_end"] = dates.dt.strftime("%Y-%m-%d")
    prepared["people"] = people.astype("int64")
    prepared = prepared.rename(columns={
        "Support Type": "support_type",
        "Accommodation Type": "accommodation_type",
        "UK Region / Nation": "uk_region",
    })
    grouped = prepared.groupby(
        ["quarter", "period_end", "support_type", "accommodation_type", "uk_region"],
        dropna=False,
        as_index=False,
    )["people"].sum()
    return grouped.sort_values(
        ["quarter", "support_type", "accommodation_type", "uk_region"],
        na_position="last",
    ).reset_index(drop=True)


def parse_work_in_progress(path):
    raw = pd.read_excel(path, sheet_name="ASY_03", header=None, engine="openpyxl")
    header_index = next(
        (index for index, row in raw.iterrows() if str(row.iloc[0]).strip() == "Quarter"), None
    )
    if header_index is None:
        raise ValueError("Could not find the ASY_03 quarter header in the transparency workbook.")
    columns = [
        (index, str(value).strip())
        for index, value in enumerate(raw.iloc[header_index])
        if pd.notna(value) and str(value).strip()
    ]
    column_names = [name for _, name in columns]
    if "Total Work In Progress" not in column_names:
        raise ValueError("The ASY_03 workbook no longer has a Total Work In Progress column.")
    if len(set(column_names)) != len(column_names):
        raise ValueError("The ASY_03 workbook contains duplicate column headings.")
    rows = []
    for _, row in raw.iloc[header_index + 1:].iterrows():
        quarter = str(row.iloc[0]).strip()
        if not pd.notna(row.iloc[0]) or not re.fullmatch(r"20\d{2} Q[1-4]", quarter):
            continue
        output = {"Quarter": quarter, "period_end": quarter_end(quarter)}
        for index, column in columns:
            if index == 0:
                continue
            output[column] = count_value(row.iloc[index])
        rows.append(output)
    if not rows:
        raise ValueError("ASY_03 contains no dated work-in-progress observations.")
    work_in_progress = pd.DataFrame(rows)
    for column in work_in_progress.columns:
        if column not in {"Quarter", "period_end"}:
            work_in_progress[column] = pd.array(work_in_progress[column], dtype="Int64")
    return work_in_progress


def parse_initial_decision_wip(path):
    raw = pd.read_excel(path, sheet_name="ASY_02", header=None, engine="openpyxl")
    header_index = next(
        (index for index, row in raw.iterrows() if str(row.iloc[0]).strip() == "Quarter"), None
    )
    if header_index is None:
        raise ValueError("Could not find the ASY_02 quarter header in the transparency workbook.")
    columns = [str(value).strip() if pd.notna(value) else "" for value in raw.iloc[header_index]]
    required = ["Quarter", "Total", "Less than 3 months", "3-6 months", "6-12 months", "12 months+"]
    if not set(required).issubset(columns):
        raise ValueError("The ASY_02 workbook table is missing its total or waiting-time bands.")
    positions = {name: columns.index(name) for name in required}
    output_names = {
        "Total": "initial_decision_cases",
        "Less than 3 months": "waiting_less_than_3_months",
        "3-6 months": "waiting_3_to_6_months",
        "6-12 months": "waiting_6_to_12_months",
        "12 months+": "waiting_12_months_or_more",
    }
    rows = []
    for _, row in raw.iloc[header_index + 1:].iterrows():
        quarter = str(row.iloc[positions["Quarter"]]).strip()
        if not re.fullmatch(r"20\d{2} Q[1-4]", quarter):
            continue
        record = {"quarter": quarter, "period_end": quarter_end(quarter)}
        record.update({
            output_names[name]: count_value(row.iloc[positions[name]])
            for name in output_names
        })
        rows.append(record)
    if not rows:
        raise ValueError("ASY_02 contains no dated initial-decision WIP observations.")
    return pd.DataFrame(rows)


def parse_tribunal_caseload(path):
    raw = pd.read_excel(path, sheet_name="FIA_4", header=None, engine="odf")
    header_index = next(
        (index for index, row in raw.iterrows()
         if "Financial Year" in row.astype(str).str.strip().tolist()
         and "Quarter" in row.astype(str).str.strip().tolist()),
        None,
    )
    if header_index is None:
        raise ValueError("Could not find the FIA_4 financial-year and quarter header.")
    columns = [str(value).strip() if pd.notna(value) else "" for value in raw.iloc[header_index]]
    required = {"Financial Year", "Quarter", "Total"}
    if not required.issubset(columns):
        raise ValueError("FIA_4 is missing its financial year, quarter or total columns.")
    asylum_column = next(
        (column for column in columns if column.startswith("Asylum/Protection/Revocation of Protection")), None
    )
    if asylum_column is None:
        raise ValueError("FIA_4 is missing the Asylum/Protection/Revocation of Protection column.")
    positions = {name: columns.index(name) for name in required | {asylum_column}}
    rows = []
    financial_year = None
    for _, row in raw.iloc[header_index + 1:].iterrows():
        candidate = str(row.iloc[positions["Financial Year"]]).strip()
        if re.fullmatch(r"20\d{2}/\d{2}", candidate):
            financial_year = candidate
        quarter_label = str(row.iloc[positions["Quarter"]]).strip()
        if financial_year is None or not re.fullmatch(r"Q[1-4]", quarter_label):
            continue
        financial_quarter = int(quarter_label[1])
        calendar_year = int(financial_year[:4]) + (financial_quarter == 4)
        calendar_quarter = financial_quarter % 4 + 1
        quarter = f"{calendar_year} Q{calendar_quarter}"
        rows.append({
            "quarter": quarter,
            "period_end": quarter_end(quarter),
            "tribunal_total_open_cases": count_value(row.iloc[positions["Total"]]),
            "tribunal_asylum_protection_open_cases": count_value(row.iloc[positions[asylum_column]]),
        })
    result = pd.DataFrame(rows)
    if result.empty or result["quarter"].duplicated().any():
        raise ValueError("FIA_4 contains no quarterly observations or duplicate calendar quarters.")
    return result.sort_values("quarter").reset_index(drop=True)


def parse_queue_indicators(transparency_path, tribunal_path):
    initial_decision = parse_initial_decision_wip(transparency_path)
    tribunal = parse_tribunal_caseload(tribunal_path)
    result = initial_decision.merge(
        tribunal, on=["quarter", "period_end"], how="left", validate="one_to_one"
    )
    tribunal_columns = ["tribunal_total_open_cases", "tribunal_asylum_protection_open_cases"]
    if result[tribunal_columns].isna().any().any():
        raise ValueError("FIA_4 is missing one or more caseload values for quarters covered by ASY_02.")
    if result["tribunal_asylum_protection_open_cases"].gt(result["tribunal_total_open_cases"]).any():
        raise ValueError("The FIA_4 asylum/protection caseload cannot exceed the total open caseload.")
    return result


def require_equal(actual, expected, message):
    if actual != expected:
        raise ValueError(f"{message}: extracted {actual:,}; Asy_00a reports {expected:,}.")


def validate_support_against_summary(support, tables):
    flows = tables["Asy_00a"]
    quarterly_totals = support.groupby("quarter")["people"].sum()
    hotel_totals = support.loc[
        support["accommodation_type"] == "Contingency Accommodation - Hotel"
    ].groupby("quarter")["people"].sum()

    for year in range(2022, 2026):
        quarter = f"{year} Q4"
        for values, label in [
            (quarterly_totals, "Asylum seekers in receipt of support"),
            (hotel_totals, "Of which accommodated in hotels"),
        ]:
            expected = value_for(flows, label, str(year))
            actual = values.get(quarter)
            if expected is not None:
                if actual is None:
                    raise ValueError(f"The support workbook is missing the {quarter} {label.lower()} observation.")
                require_equal(int(actual), int(expected), f"{quarter} {label} does not reconcile")

    latest = "2026 Q2"
    latest_total = quarterly_totals.get(latest)
    latest_hotels = hotel_totals.get(latest)
    if latest_total is None or latest_hotels is None:
        raise ValueError("The support workbook is missing its June 2026 total or hotel observation.")
    require_equal(
        int(latest_total), int(value_for(flows, "Asylum seekers in receipt of support", "Year ending June 2026")),
        "June 2026 total support does not reconcile",
    )
    require_equal(
        int(latest_hotels), int(value_for(flows, "Of which accommodated in hotels", "Year ending June 2026")),
        "June 2026 hotel accommodation does not reconcile",
    )


def validate_against_summary(quarterly, work_in_progress, support, queue_indicators, tables):
    flows = tables["Asy_00a"]
    measures = {
        "claims": "People claiming asylum",
        "substantive_decisions": "People receiving initial decisions",
        "grants": "Grants of protection or other leave",
        "refusals": "Refusals",
        "withdrawals": "Withdrawals",
        "enforced_returns": "Enforced",
        "voluntary_returns": "Voluntary",
        "asylum_related_returns": "Asylum-related returns",
    }
    quarterly = quarterly.copy()
    quarterly["year"] = quarterly["quarter"].str[:4].astype(int)
    for year in range(2010, 2026):
        annual = quarterly.loc[quarterly["year"] == year]
        for measure, label in measures.items():
            extracted = int(annual[measure].sum())
            expected = int(value_for(flows, label, str(year)))
            require_equal(extracted, expected, f"{measure} does not reconcile for {year}")

    latest = quarterly.loc[quarterly["quarter"].isin(["2025 Q3", "2025 Q4", "2026 Q1", "2026 Q2"])]
    if len(latest) != 4:
        raise ValueError("The quarterly files must cover all four quarters in the year ending June 2026.")
    latest_column = "Year ending June 2026"
    for measure, label in measures.items():
        extracted = int(latest[measure].sum())
        expected = int(value_for(flows, label, latest_column))
        require_equal(extracted, expected, f"{measure} does not reconcile for the year ending June 2026")

    latest_stock = quarterly.loc[quarterly["quarter"] == "2026 Q2", "people_awaiting_initial_decision"]
    expected_stock = int(value_for(flows, "People awaiting an initial decision", latest_column))
    if latest_stock.empty or pd.isna(latest_stock.iloc[0]):
        raise ValueError("The pending-stock workbook is missing the June 2026 observation.")
    require_equal(int(latest_stock.iloc[0]), expected_stock, "June 2026 initial-decision stock does not reconcile")
    if quarterly["main_applicants_awaiting_initial_decision"].isna().ne(
        quarterly["people_awaiting_initial_decision"].isna()
    ).any():
        raise ValueError("The pending people and main-applicant series must cover the same quarters.")
    observed_stock = quarterly["people_awaiting_initial_decision"].dropna()
    observed_main_applicants = quarterly.loc[
        quarterly["people_awaiting_initial_decision"].notna(), "main_applicants_awaiting_initial_decision"
    ]
    if observed_main_applicants.gt(observed_stock).any():
        raise ValueError("Main-applicant pending cases cannot exceed the pending people count.")
    main_applicant_2024 = quarterly.loc[
        quarterly["quarter"] == "2024 Q2", "main_applicants_awaiting_initial_decision"
    ]
    if main_applicant_2024.empty or int(main_applicant_2024.iloc[0]) != 85839:
        raise ValueError("The D03 June 2024 main-applicant pending count changed from 85,839.")
    main_applicant_2026 = quarterly.loc[
        quarterly["quarter"] == "2026 Q2", "main_applicants_awaiting_initial_decision"
    ]
    expected_cases = int(value_for(flows, "Cases awaiting an initial decision", latest_column))
    if main_applicant_2026.empty:
        raise ValueError("The pending-stock workbook is missing the June 2026 main-applicant observation.")
    require_equal(
        int(main_applicant_2026.iloc[0]), expected_cases,
        "June 2026 main-applicant pending cases do not reconcile",
    )
    wip = work_in_progress.loc[work_in_progress["Quarter"] == "2024 Q2", "Total Work In Progress"]
    if wip.empty or int(wip.iloc[0]) != 224742:
        raise ValueError("ASY_03 no longer reports 224,742 work-in-progress cases in June 2024.")
    expected_queue_quarters = [f"{year} Q{quarter}" for year in range(2016, 2027)
                               for quarter in range(1, 5)
                               if (year > 2016 or quarter >= 4) and (year < 2026 or quarter <= 2)]
    if queue_indicators["quarter"].tolist() != expected_queue_quarters:
        raise ValueError("Queue indicators must cover 2016 Q4 through 2026 Q2 without gaps.")
    waiting_bands = [
        "waiting_less_than_3_months", "waiting_3_to_6_months",
        "waiting_6_to_12_months", "waiting_12_months_or_more",
    ]
    if queue_indicators[waiting_bands].isna().any().any():
        raise ValueError("ASY_02 is missing a waiting-time band in the queue-indicator extract.")
    if queue_indicators[waiting_bands].sum(axis=1).ne(queue_indicators["initial_decision_cases"]).any():
        raise ValueError("ASY_02 waiting-time bands do not reconcile to the initial-decision total.")
    work_in_progress_by_quarter = work_in_progress.set_index("Quarter")
    for year in range(2017, 2025):
        quarter = f"{year} Q2"
        observed = queue_indicators.loc[queue_indicators["quarter"] == quarter, "initial_decision_cases"]
        expected = work_in_progress_by_quarter.loc[quarter, "Awaiting Initial Asylum Decision"]
        if observed.empty or pd.isna(expected):
            raise ValueError(f"ASY_02 or ASY_03 is missing the June {year} initial-decision count.")
        require_equal(int(observed.iloc[0]), int(expected), f"ASY_02 and ASY_03 differ in June {year}")
    fixed_values = {
        ("2024 Q2", "initial_decision_cases"): 87217,
        ("2026 Q2", "initial_decision_cases"): 33514,
        ("2024 Q2", "tribunal_asylum_protection_open_cases"): 33227,
        ("2026 Q2", "tribunal_asylum_protection_open_cases"): 90341,
    }
    for (quarter, column), expected in fixed_values.items():
        observed = queue_indicators.loc[queue_indicators["quarter"] == quarter, column]
        if observed.empty:
            raise ValueError(f"The queue-indicator extract is missing {quarter} {column}.")
        require_equal(int(observed.iloc[0]), expected, f"The published {quarter} {column} changed")
    if queue_indicators["tribunal_asylum_protection_open_cases"].gt(
        queue_indicators["tribunal_total_open_cases"]
    ).any():
        raise ValueError("FIA_4 asylum/protection caseloads exceed the total caseload.")
    validate_support_against_summary(support, tables)


def manifest_sources(old_manifest, workbook_hashes, quarterly_hash, wip_hash, support_hash, queue_hash,
                     update_extract_pins):
    old_workbooks = old_manifest.get("workbooks", {})
    for name, digest in workbook_hashes.items():
        expected = old_workbooks.get(name, {}).get("sha256")
        if expected and digest != expected:
            raise ValueError(f"Pinned {name} workbook SHA-256 changed; review before refreshing quarterly outputs.")
    expected_quarterly = old_manifest.get("quarterly_extract", {}).get("sha256")
    expected_wip = old_manifest.get("work_in_progress_extract", {}).get("sha256")
    expected_support = old_manifest.get("support_extract", {}).get("sha256")
    expected_queue = old_manifest.get("queue_indicators_extract", {}).get("sha256")
    if expected_quarterly and quarterly_hash != expected_quarterly and not update_extract_pins:
        raise ValueError("The quarterly extract changed; review it before updating the source manifest.")
    if expected_wip and wip_hash != expected_wip and not update_extract_pins:
        raise ValueError("The work-in-progress extract changed; review it before updating the source manifest.")
    if expected_support and support_hash != expected_support and not update_extract_pins:
        raise ValueError("The support extract changed; review it before updating the source manifest.")
    if expected_queue and queue_hash != expected_queue and not update_extract_pins:
        raise ValueError("The queue-indicator extract changed; review it before updating the source manifest.")

    return {
        "release": "Year ending June 2026",
        "source_pages": {
            "asylum_and_returns": SOURCE_PAGE,
            "transparency": TRANSPARENCY_PAGE,
            "tribunals": TRIBUNAL_PAGE,
        },
        "retrieved": old_manifest.get("retrieved") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "workbooks": {
            name: {
                "url": source["url"],
                "filename": source["filename"],
                "sha256": workbook_hashes[name],
            }
            for name, source in SOURCES.items()
        },
        "quarterly_extract": {"file": "quarterly-extract.csv", "sha256": quarterly_hash},
        "work_in_progress_extract": {"file": "asylum-work-in-progress.csv", "sha256": wip_hash},
        "support_extract": {"file": "support-accommodation-extract.csv", "sha256": support_hash},
        "queue_indicators_extract": {"file": "queue-indicators.csv", "sha256": queue_hash},
    }


def prepare(update_extract_pins=False):
    old_manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.exists() else {}
    old_workbooks = old_manifest.get("workbooks", {})
    paths = {}
    hashes = {}
    for name, source in SOURCES.items():
        path, digest = get_workbook(name, source, old_workbooks.get(name, {}).get("sha256"))
        paths[name] = path
        hashes[name] = digest

    quarterly = parse_quarterly_sources(paths)
    work_in_progress = parse_work_in_progress(paths["transparency"])
    support = parse_support_sources(paths["support"])
    queue_indicators = parse_queue_indicators(paths["transparency"], paths["tribunals"])
    _, tables = load_tables()
    validate_against_summary(quarterly, work_in_progress, support, queue_indicators, tables)

    quarterly_bytes = quarterly.to_csv(index=False, lineterminator="\n", na_rep="").encode("utf-8")
    wip_bytes = work_in_progress.to_csv(index=False, lineterminator="\n", na_rep="").encode("utf-8")
    support_bytes = support.to_csv(index=False, lineterminator="\n", na_rep="").encode("utf-8")
    queue_bytes = queue_indicators.to_csv(index=False, lineterminator="\n", na_rep="").encode("utf-8")
    quarterly_hash = hashlib.sha256(quarterly_bytes).hexdigest()
    wip_hash = hashlib.sha256(wip_bytes).hexdigest()
    support_hash = hashlib.sha256(support_bytes).hexdigest()
    queue_hash = hashlib.sha256(queue_bytes).hexdigest()
    manifest = manifest_sources(
        old_manifest, hashes, quarterly_hash, wip_hash, support_hash, queue_hash, update_extract_pins
    )

    QUARTERLY_PATH.write_bytes(quarterly_bytes)
    WORK_IN_PROGRESS_PATH.write_bytes(wip_bytes)
    SUPPORT_PATH.write_bytes(support_bytes)
    QUEUE_INDICATORS_PATH.write_bytes(queue_bytes)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        "Prepared quarterly flows, 14 ASY_03 snapshots, support/accommodation and queue indicators; "
        "flows and source reconciliations validated."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-extract-pins",
        action="store_true",
        help="accept reviewed changes to the generated CSV extracts and update their manifest hashes",
    )
    prepare(update_extract_pins=parser.parse_args().update_extract_pins)