"""Prepare pinned quarterly asylum flows, return and work-in-progress data."""
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
MANIFEST_PATH = ROOT / "data" / "raw" / "quarterly-sources.json"
SOURCE_PAGE = "https://www.gov.uk/government/statistical-data-sets/immigration-system-statistics-data-tables"
TRANSPARENCY_PAGE = "https://www.gov.uk/government/statistical-data-sets/migration-transparency-data"
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
}
QUARTERLY_COLUMNS = [
    "quarter", "period_end", "claims", "grants", "refusals", "substantive_decisions",
    "withdrawals", "admin_outcomes", "enforced_returns", "voluntary_returns",
    "refused_entry_returns", "asylum_related_returns", "people_awaiting_initial_decision",
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
        "pending": (pending_data, {"Date (as at...)", "Application stage", "Claims"}),
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
        })
    quarterly = pd.DataFrame(rows, columns=QUARTERLY_COLUMNS)
    quarterly["people_awaiting_initial_decision"] = pd.array(
        quarterly["people_awaiting_initial_decision"], dtype="Int64"
    )
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
    columns = [str(value).strip() if pd.notna(value) else "" for value in raw.iloc[header_index]]
    if "Total Work In Progress" not in columns:
        raise ValueError("The ASY_03 workbook no longer has a Total Work In Progress column.")
    if len(set(columns)) != len(columns):
        raise ValueError("The ASY_03 workbook contains duplicate column headings.")
    rows = []
    for _, row in raw.iloc[header_index + 1:].iterrows():
        quarter = str(row.iloc[0]).strip()
        if not pd.notna(row.iloc[0]) or not re.fullmatch(r"20\d{2} Q[1-4]", quarter):
            continue
        output = {"Quarter": quarter, "period_end": quarter_end(quarter)}
        for index, column in enumerate(columns[1:], start=1):
            output[column] = count_value(row.iloc[index])
        rows.append(output)
    if not rows:
        raise ValueError("ASY_03 contains no dated work-in-progress observations.")
    work_in_progress = pd.DataFrame(rows)
    for column in work_in_progress.columns:
        if column not in {"Quarter", "period_end"}:
            work_in_progress[column] = pd.array(work_in_progress[column], dtype="Int64")
    return work_in_progress


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


def validate_against_summary(quarterly, work_in_progress, support, tables):
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
    wip = work_in_progress.loc[work_in_progress["Quarter"] == "2024 Q2", "Total Work In Progress"]
    if wip.empty or int(wip.iloc[0]) != 224742:
        raise ValueError("ASY_03 no longer reports 224,742 work-in-progress cases in June 2024.")
    validate_support_against_summary(support, tables)


def manifest_sources(old_manifest, workbook_hashes, quarterly_hash, wip_hash, support_hash, update_extract_pins):
    old_workbooks = old_manifest.get("workbooks", {})
    for name, digest in workbook_hashes.items():
        expected = old_workbooks.get(name, {}).get("sha256")
        if expected and digest != expected:
            raise ValueError(f"Pinned {name} workbook SHA-256 changed; review before refreshing quarterly outputs.")
    expected_quarterly = old_manifest.get("quarterly_extract", {}).get("sha256")
    expected_wip = old_manifest.get("work_in_progress_extract", {}).get("sha256")
    expected_support = old_manifest.get("support_extract", {}).get("sha256")
    if expected_quarterly and quarterly_hash != expected_quarterly and not update_extract_pins:
        raise ValueError("The quarterly extract changed; review it before updating the source manifest.")
    if expected_wip and wip_hash != expected_wip and not update_extract_pins:
        raise ValueError("The work-in-progress extract changed; review it before updating the source manifest.")
    if expected_support and support_hash != expected_support and not update_extract_pins:
        raise ValueError("The support extract changed; review it before updating the source manifest.")

    return {
        "release": "Year ending June 2026",
        "source_pages": {"asylum_and_returns": SOURCE_PAGE, "transparency": TRANSPARENCY_PAGE},
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
    _, tables = load_tables()
    validate_against_summary(quarterly, work_in_progress, support, tables)

    quarterly_bytes = quarterly.to_csv(index=False, lineterminator="\n", na_rep="").encode("utf-8")
    wip_bytes = work_in_progress.to_csv(index=False, lineterminator="\n", na_rep="").encode("utf-8")
    support_bytes = support.to_csv(index=False, lineterminator="\n", na_rep="").encode("utf-8")
    quarterly_hash = hashlib.sha256(quarterly_bytes).hexdigest()
    wip_hash = hashlib.sha256(wip_bytes).hexdigest()
    support_hash = hashlib.sha256(support_bytes).hexdigest()
    manifest = manifest_sources(old_manifest, hashes, quarterly_hash, wip_hash, support_hash, update_extract_pins)

    QUARTERLY_PATH.write_bytes(quarterly_bytes)
    WORK_IN_PROGRESS_PATH.write_bytes(wip_bytes)
    SUPPORT_PATH.write_bytes(support_bytes)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        "Prepared quarterly flows, 14 ASY_03 snapshots and quarterly support/accommodation data; "
        "flow and support totals reconcile to Asy_00a."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-extract-pins",
        action="store_true",
        help="accept reviewed changes to the generated CSV extracts and update their manifest hashes",
    )
    prepare(update_extract_pins=parser.parse_args().update_extract_pins)