"""Parse the pinned Home Office asylum tables and build report datasets."""
import hashlib
import json
import math
import os
import re
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "data" / "raw" / "asylum-summary-jun-2026.ods"
SOURCE = ROOT / "data" / "raw" / "source.json"
QUARTERLY_MANIFEST = ROOT / "data" / "raw" / "quarterly-sources.json"
ASSETS = ROOT / "assets"
DERIVED = ROOT / "data" / "derived"
QUARTERLY_COLUMNS = [
    "quarter", "period_end", "claims", "grants", "refusals", "substantive_decisions",
    "withdrawals", "admin_outcomes", "enforced_returns", "voluntary_returns",
    "refused_entry_returns", "asylum_related_returns", "people_awaiting_initial_decision",
    "main_applicants_awaiting_initial_decision",
]
SUPPORT_COLUMNS = [
    "quarter", "period_end", "support_type", "accommodation_type", "uk_region", "people",
]
WIP_STAGE_COLUMNS = [
    "Awaiting Initial Asylum Decision", "Post Decision", "Asylum Appeal Outstanding",
    "Subject to Removal Action", "On Hold", "Further Leave Application Outstanding",
]
INADMISSIBILITY_ROWS = {
    "identified": "Total identified for consideration on inadmissibility grounds",
    "notices_of_intent": "Notice of intent issued",
    "decisions_served": "Inadmissibility decision served",
    "removals": "Removals",
    "subsequently_admitted": "Subsequently admitted into UK asylum process",
}

SHEETS = {
    "Asy_00a": "Date / As at the end of...",
    "Asy_00b": "Nationality",
    "Asy_01a": "Date of claim",
    "Asy_01b": "Nationality",
    "Asy_01c": "Route prior to claim",
    "Asy_01d": "Nationality",
    "Asy_02a": "Date of initial decision",
    "Asy_02b": "Date of initial decision",
    "Asy_02c": "Outcome",
    "Asy_02d": "Nationality",
    "Asy_02e": "Date",
    "Asy_03a": "As at end of...",
    "Asy_03b": "As at...",
    "Asy_03c": "As at...",
    "Asy_04": "Year of claim",
    "Asy_05": "Date of first age assessment",
    "Asy_09a": "As at the end of...",
    "Asy_09b": "As at the end of...",
}

INK = "#20343a"
TEAL = "#247367"
PURPLE = "#8574bd"
GOLD = "#d68d38"
MUTED = "#65767a"
GRID = "#e2e9e4"
COUNT_AXIS_K_THRESHOLD = 10_000
AGE_BAND_TOLERANCE = 7


def header_text(value):
    if pd.isna(value):
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(float(value)) and float(value).is_integer():
            return str(int(value))
    text = str(value).strip()
    return re.sub(r"^(20\d{2})\.0$", r"\1", text)


def cell_value(value):
    if pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            return None
        return int(number) if number.is_integer() else number
    text = str(value).strip()
    if text.lower() in {"z", ":", "..", "n/a", "na"}:
        return None
    if re.fullmatch(r"-?\d[\d,]*(?:\.\d+)?", text):
        number = float(text.replace(",", ""))
        return int(number) if number.is_integer() else number
    return text


def parse_table(sheet, raw):
    """Convert one summary-table worksheet to rows keyed by its printed headers."""
    marker = SHEETS[sheet]
    header_index = next(
        (index for index, row in raw.iterrows()
         if pd.notna(row.iloc[0]) and header_text(row.iloc[0]).startswith(marker)),
        None,
    )
    if header_index is None:
        raise ValueError(f"Could not locate the '{marker}' header in {sheet}.")

    headers = [header_text(value) for value in raw.iloc[header_index, 1:]]
    if any(not name for name in headers):
        raise ValueError(f"{sheet} has a blank column heading.")
    if len(set(headers)) != len(headers):
        raise ValueError(f"{sheet} has duplicate column headings: {headers}.")

    rows = []
    for _, row in raw.iloc[header_index + 1:].iterrows():
        if pd.isna(row.iloc[0]):
            continue
        label = str(row.iloc[0]).strip()
        if not label:
            continue
        rows.append({
            "label": label,
            "values": {name: cell_value(row.iloc[index + 1]) for index, name in enumerate(headers)},
        })

    if not rows:
        raise ValueError(f"{sheet} contains no data rows after its header.")
    return {
        "title": cell_value(raw.iloc[0, 0]),
        "header": marker,
        "columns": headers,
        "rows": rows,
    }


def load_tables():
    metadata = json.loads(SOURCE.read_text(encoding="utf-8"))
    actual_hash = hashlib.sha256(WORKBOOK.read_bytes()).hexdigest()
    if actual_hash != metadata.get("sha256"):
        raise ValueError("Home Office workbook SHA-256 differs from data/raw/source.json.")

    workbook = pd.ExcelFile(WORKBOOK, engine="odf")
    missing = sorted(set(SHEETS) - set(workbook.sheet_names))
    if missing:
        raise ValueError("Workbook is missing expected sheets: " + ", ".join(missing))
    tables = {
        sheet: parse_table(sheet, pd.read_excel(workbook, sheet_name=sheet, header=None))
        for sheet in SHEETS
    }
    return metadata, tables


def row_for(table, label):
    return next((row for row in table["rows"] if row["label"] == label), None)


def value_for(table, label, column):
    row = row_for(table, label)
    if row is None:
        raise ValueError(f"Missing row '{label}' in a parsed table.")
    if column not in row["values"]:
        raise ValueError(f"Missing column '{column}' for '{label}'.")
    return row["values"][column]


def age_group_rows(table, group):
    group_labels = {
        "Total people", "Main applicants", "Unaccompanied asylum-seeking children (UASC)",
    }
    rows = table["rows"]
    start = next((index for index, row in enumerate(rows) if row["label"] == group), None)
    if start is None:
        raise ValueError(f"Missing age group '{group}' in Asy_01a.")
    end = next(
        (index for index in range(start + 1, len(rows))
         if rows[index]["label"] in group_labels or rows[index]["label"] == "UASC as a % of all claimants"),
        len(rows),
    )
    return {row["label"]: row for row in rows[start:end]}


def optional_value(table, label, column):
    row = row_for(table, label)
    return row["values"].get(column) if row else None


def numeric(value, context):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"Expected a numeric value for {context}; found {value!r}.")
    return float(value)


def inadmissibility_count(table, label, column):
    value = numeric(value_for(table, label, column), f"{label} in {column}")
    if value < 0 or not value.is_integer():
        raise ValueError(f"Expected a non-negative whole-number count for {label} in {column}; found {value!r}.")
    return int(value)


def load_quarterly_data():
    manifest = json.loads(QUARTERLY_MANIFEST.read_text(encoding="utf-8"))
    extracts = {}
    for key in ("quarterly_extract", "work_in_progress_extract"):
        entry = manifest.get(key, {})
        path = ROOT / "data" / "raw" / entry.get("file", "")
        if not path.is_file():
            raise ValueError(f"Pinned quarterly data file is missing: {path}.")
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_hash != entry.get("sha256"):
            raise ValueError(f"Quarterly data SHA-256 differs from quarterly-sources.json: {path.name}.")
        extracts[key] = path

    quarterly = pd.read_csv(extracts["quarterly_extract"], dtype={"quarter": str})
    work_in_progress = pd.read_csv(extracts["work_in_progress_extract"], dtype={"Quarter": str})
    if list(quarterly.columns) != QUARTERLY_COLUMNS:
        raise ValueError("The quarterly extract has unexpected or missing columns.")
    required_wip_columns = {"Quarter", "period_end", "Total Work In Progress", *WIP_STAGE_COLUMNS}
    if not required_wip_columns.issubset(work_in_progress.columns):
        raise ValueError("The ASY_03 extract is missing its quarter, date, total or stage columns.")
    return quarterly, work_in_progress


def load_support_data():
    manifest = json.loads(QUARTERLY_MANIFEST.read_text(encoding="utf-8"))
    entry = manifest.get("support_extract", {})
    path = ROOT / "data" / "raw" / entry.get("file", "")
    if not path.is_file():
        raise ValueError(f"Pinned support data file is missing: {path}.")
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_hash != entry.get("sha256"):
        raise ValueError(f"Support data SHA-256 differs from quarterly-sources.json: {path.name}.")

    support = pd.read_csv(path, dtype={"quarter": str, "period_end": str})
    if list(support.columns) != SUPPORT_COLUMNS:
        raise ValueError("The support extract has unexpected or missing columns.")
    support["people"] = pd.to_numeric(support["people"], errors="coerce")
    return support


def validate_quarterly_data(tables, quarterly, work_in_progress):
    expected_quarters = [f"{year} Q{quarter}" for year in range(2010, 2027)
                         for quarter in range(1, 5) if year < 2026 or quarter <= 2]
    if quarterly["quarter"].tolist() != expected_quarters:
        raise ValueError("The quarterly extract must cover each quarter from 2010 Q1 through 2026 Q2.")
    if quarterly["substantive_decisions"].ne(quarterly["grants"] + quarterly["refusals"]).any():
        raise ValueError("Quarterly substantive decisions do not equal grants plus refusals.")
    if quarterly["asylum_related_returns"].ne(
        quarterly["enforced_returns"] + quarterly["voluntary_returns"]
    ).any():
        raise ValueError("Quarterly asylum-related returns must exclude refused-entry departures.")
    if pd.notna(quarterly["people_awaiting_initial_decision"].iloc[0]):
        raise ValueError("The quarterly stock series should start in 2010 Q2, not 2010 Q1.")
    if quarterly["people_awaiting_initial_decision"].iloc[1:].isna().any():
        raise ValueError("The pending-stock workbook is missing one or more quarterly observations.")
    people_pending = quarterly["people_awaiting_initial_decision"]
    main_applicants_pending = quarterly["main_applicants_awaiting_initial_decision"]
    if main_applicants_pending.isna().ne(people_pending.isna()).any():
        raise ValueError("The pending people and main-applicant series must cover the same quarters.")
    if main_applicants_pending.gt(people_pending).any():
        raise ValueError("Main-applicant pending cases cannot exceed the pending people count.")

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
    years = quarterly["quarter"].str[:4].astype(int)
    for year in range(2010, 2026):
        annual = quarterly.loc[years == year]
        for measure, label in measures.items():
            actual = int(annual[measure].sum())
            expected = int(value_for(flows, label, str(year)))
            if actual != expected:
                raise ValueError(f"Quarterly {measure} does not reconcile to Asy_00a in {year}.")

    latest = quarterly.loc[quarterly["quarter"].isin(
        ["2025 Q3", "2025 Q4", "2026 Q1", "2026 Q2"]
    )]
    if len(latest) != 4:
        raise ValueError("The quarterly extract is missing a period in the year ending June 2026.")
    for measure, label in measures.items():
        actual = int(latest[measure].sum())
        expected = int(value_for(flows, label, "Year ending June 2026"))
        if actual != expected:
            raise ValueError(f"Quarterly {measure} does not reconcile to the June 2026 rolling year.")

    latest_stock = quarterly.loc[quarterly["quarter"] == "2026 Q2", "people_awaiting_initial_decision"]
    expected_stock = int(value_for(flows, "People awaiting an initial decision", "Year ending June 2026"))
    if latest_stock.empty or int(latest_stock.iloc[0]) != expected_stock:
        raise ValueError("Quarterly stock does not reconcile to the June 2026 Asy_00a headline.")
    june_2024_main_applicants = quarterly.loc[
        quarterly["quarter"] == "2024 Q2", "main_applicants_awaiting_initial_decision"
    ]
    if june_2024_main_applicants.empty or int(june_2024_main_applicants.iloc[0]) != 85839:
        raise ValueError("D03 must report 85,839 main-applicant pending cases in June 2024.")
    june_2026_main_applicants = quarterly.loc[
        quarterly["quarter"] == "2026 Q2", "main_applicants_awaiting_initial_decision"
    ]
    expected_cases = int(value_for(flows, "Cases awaiting an initial decision", "Year ending June 2026"))
    if june_2026_main_applicants.empty or int(june_2026_main_applicants.iloc[0]) != expected_cases:
        raise ValueError("D03 main-applicant pending cases do not reconcile to Asy_00a in June 2026.")

    expected_wip_quarters = [f"{year} Q2" for year in range(2011, 2025)]
    if work_in_progress["Quarter"].tolist() != expected_wip_quarters:
        raise ValueError("ASY_03 must contain its June snapshots from 2011 through 2024.")
    latest_wip = work_in_progress.loc[
        work_in_progress["Quarter"] == "2024 Q2", "Total Work In Progress"
    ]
    if latest_wip.empty or int(latest_wip.iloc[0]) != 224742:
        raise ValueError("ASY_03 must report 224,742 work-in-progress cases in June 2024.")
    stage_totals = work_in_progress[WIP_STAGE_COLUMNS].fillna(0).sum(axis=1)
    if stage_totals.ne(work_in_progress["Total Work In Progress"]).any():
        raise ValueError("ASY_03 stage counts do not reconcile to total work in progress.")
    latest_wip_stages = work_in_progress.loc[work_in_progress["Quarter"] == "2024 Q2"].iloc[0]
    if (int(latest_wip_stages["Awaiting Initial Asylum Decision"]) != 87217
            or int(latest_wip_stages["Post Decision"]) != 137525):
        raise ValueError("ASY_03 June 2024 initial-decision stages changed from the published split.")


def work_in_progress_stages(work_in_progress):
    result = work_in_progress.copy()
    total = result["Total Work In Progress"]
    awaiting = result["Awaiting Initial Asylum Decision"]
    result["not_awaiting"] = total - awaiting
    result["not_awaiting_share"] = result["not_awaiting"] / total

    decided_columns = [
        "Post Decision", "Asylum Appeal Outstanding", "Subject to Removal Action",
        "Further Leave Application Outstanding",
    ]
    result["decided_excluding_on_hold"] = result[decided_columns].fillna(0).sum(axis=1).astype("Int64")
    no_breakdown = (
        result[decided_columns].notna().sum(axis=1).eq(1)
        & result["Post Decision"].notna()
        & result["Post Decision"].eq(result["not_awaiting"])
    )
    result.loc[no_breakdown, "decided_excluding_on_hold"] = pd.NA
    result["decided_excluding_on_hold_share"] = (
        result["decided_excluding_on_hold"] / total
    )
    return result


def quarterly_flows_with_rolling_returns(quarterly):
    result = quarterly.copy()
    result["rolling_12m_returns"] = result["asylum_related_returns"].rolling(4, min_periods=4).sum()
    return result


def support_series(support):
    by_accommodation = support.groupby(
        ["quarter", "period_end", "accommodation_type"], dropna=False
    )["people"].sum().unstack("accommodation_type")
    by_accommodation = by_accommodation.rename(columns={
        "Contingency Accommodation - Hotel": "hotel",
        "N/A - Section 98 (pre-2023)": "section_98",
        "Contingency Accommodation - Other": "other_contingency",
    })
    series = by_accommodation.reset_index()
    for column in ("hotel", "section_98", "other_contingency"):
        if column not in series:
            series[column] = pd.NA
        series[column] = pd.array(series[column], dtype="Int64")
    totals = support.groupby(["quarter", "period_end"], as_index=False)["people"].sum()
    series = series.merge(totals.rename(columns={"people": "total_supported"}), on=["quarter", "period_end"])
    return series.sort_values("quarter").reset_index(drop=True)[
        ["quarter", "period_end", "hotel", "section_98", "other_contingency", "total_supported"]
    ]


def hotel_region_breakdown(support):
    hotels = support.loc[
        support["accommodation_type"] == "Contingency Accommodation - Hotel",
        ["quarter", "period_end", "uk_region", "people"],
    ].copy()
    hotels["uk_region"] = hotels["uk_region"].fillna("Not stated")
    return hotels.groupby(
        ["quarter", "period_end", "uk_region"], as_index=False, dropna=False
    )["people"].sum().sort_values(["quarter", "uk_region"]).reset_index(drop=True)


def validate_support_data(tables, support):
    if support.empty or support["people"].isna().any() or (support["people"] < 0).any():
        raise ValueError("The support extract must contain non-negative people counts.")
    keys = ["quarter", "period_end", "support_type", "accommodation_type", "uk_region"]
    if support.duplicated(keys).any():
        raise ValueError("The support extract contains duplicate category rows.")
    expected_quarters = [f"{year} Q{quarter}" for year in range(2014, 2027)
                         for quarter in range(1, 5) if year < 2026 or quarter <= 2]
    series = support_series(support)
    if series["quarter"].tolist() != expected_quarters:
        raise ValueError("The support extract must cover each quarter from 2014 Q1 through 2026 Q2.")
    hotels = series.loc[series["hotel"].notna()]
    if hotels["quarter"].tolist() != [f"{year} Q{quarter}" for year in range(2022, 2027)
                                     for quarter in range(1, 5) if year > 2022 or quarter >= 4
                                     if year < 2026 or quarter <= 2]:
        raise ValueError("The hotel series must begin in 2022 Q4 and continue through 2026 Q2.")
    section_98 = series.loc[series["section_98"].notna()]
    if section_98.empty or section_98["quarter"].iloc[-1] != "2022 Q3":
        raise ValueError("The Section 98 series should end at 2022 Q3, before hotels were separately reported.")

    flows = tables["Asy_00a"]
    for year in range(2022, 2026):
        quarter = f"{year} Q4"
        row = series.loc[series["quarter"] == quarter].iloc[0]
        for column, label in [
            ("total_supported", "Asylum seekers in receipt of support"),
            ("hotel", "Of which accommodated in hotels"),
        ]:
            expected = value_for(flows, label, str(year))
            if expected is not None and int(row[column]) != int(expected):
                raise ValueError(f"Quarterly {quarter} {label} does not reconcile to Asy_00a.")

    latest = series.loc[series["quarter"] == "2026 Q2"].iloc[0]
    if int(latest["hotel"]) != int(value_for(flows, "Of which accommodated in hotels", "Year ending June 2026")):
        raise ValueError("Quarterly June 2026 hotel accommodation does not reconcile to Asy_00a.")
    if int(latest["total_supported"]) != int(value_for(flows, "Asylum seekers in receipt of support", "Year ending June 2026")):
        raise ValueError("Quarterly June 2026 total support does not reconcile to Asy_00a.")

    regions = hotel_region_breakdown(support)
    for quarter in hotels["quarter"]:
        regional_total = int(regions.loc[regions["quarter"] == quarter, "people"].sum())
        national_total = int(series.loc[series["quarter"] == quarter, "hotel"].iloc[0])
        if regional_total != national_total:
            raise ValueError(f"Regional hotel counts do not sum to the national total in {quarter}.")


def validate_tables(tables):
    flows = tables["Asy_00a"]
    years = [str(year) for year in range(2010, 2026)]
    if not all(year in flows["columns"] for year in years):
        raise ValueError("Asy_00a must include every calendar year from 2010 through 2025.")
    for year in years:
        grants = numeric(value_for(flows, "Grants of protection or other leave", year), f"grants in {year}")
        refusals = numeric(value_for(flows, "Refusals", year), f"refusals in {year}")
        decisions = numeric(value_for(flows, "People receiving initial decisions", year), f"initial decisions in {year}")
        if grants + refusals != decisions:
            raise ValueError(f"Asy_00a grants and refusals do not reconcile to initial decisions in {year}.")

    latest = "Year ending June 2026"
    if latest not in flows["columns"]:
        raise ValueError("Asy_00a is missing its June 2026 comparison column.")
    rate = numeric(value_for(flows, "Grant rate at initial decision", latest), "June 2026 initial grant rate")
    if not 0 <= rate <= 1:
        raise ValueError("The published initial grant rate must be a fraction from zero to one.")

    boats = tables["Asy_01c"]
    if numeric(value_for(boats, "Small Boat", latest), "small-boat claims") <= 0:
        raise ValueError("The June 2026 small-boat claims figure must be positive.")
    nationality_routes = tables["Asy_01d"]
    if value_for(nationality_routes, "Total", "Small Boat") != value_for(boats, "Small Boat", latest):
        raise ValueError("Asy_01c and Asy_01d small-boat totals do not reconcile for June 2026.")

    claims_columns = [*years, "Year ending June 2025", latest]
    age_table = tables["Asy_01a"]
    age_rows = age_group_rows(age_table, "Total people")
    age_categories = ["13 and under", "14 to 15", "16 to 17", "18 and over"]
    for column in claims_columns:
        age_total = numeric(age_rows["Total people"]["values"][column], f"total people in {column}")
        age_sum = sum(numeric(age_rows[label]["values"][column], f"{label} in {column}")
                      for label in age_categories)
        if abs(age_total - age_sum) > AGE_BAND_TOLERANCE:
            raise ValueError(f"Asy_01a age bands do not reconcile to total people in {column}.")

    nationality_table = tables["Asy_01b"]
    nationality_labels = [row["label"] for row in nationality_table["rows"]
                          if row["label"] not in {"Other", "Total"}]
    for column in claims_columns:
        nationality_sum = sum(numeric(value_for(nationality_table, label, column),
                                      f"{label} claims in {column}")
                              for label in [*nationality_labels, "Other"])
        if nationality_sum != value_for(nationality_table, "Total", column):
            raise ValueError(f"Asy_01b nationality rows do not reconcile in {column}.")

    route_categories = [
        "Small Boat", "Clandestine", "Entered Without Relevant Documentation",
        "Visas and Other Leave", "Other",
    ]
    route_periods = [*[str(year) for year in range(2018, 2026)], "Year ending June 2025", latest]
    for column in route_periods:
        route_sum = sum(numeric(value_for(boats, label, column), f"{label} claims in {column}")
                        for label in route_categories)
        if route_sum != value_for(boats, "Total", column):
            raise ValueError(f"Asy_01c route categories do not reconcile in {column}.")

    for row in nationality_routes["rows"]:
        route_sum = sum(numeric(row["values"][label], f"{label} for {row['label']}")
                        for label in route_categories)
        if route_sum != row["values"]["Total"]:
            raise ValueError(f"Asy_01d route categories do not reconcile for {row['label']}.")

    periods = [*years, "Year ending June 2025", latest]
    grant_table = tables["Asy_02a"]
    grant_components = [
        "Refugee Permission", "Temporary Refugee Permission", "Humanitarian Protection",
        "Discretionary Leave", "UASC Leave", "Other Grants",
    ]
    for column in periods:
        grants = sum(
            0 if value_for(grant_table, label, column) is None
            else numeric(value_for(grant_table, label, column), f"{label} grants in {column}")
            for label in grant_components
        )
        published_grants = numeric(
            value_for(grant_table, "Asylum-related grants", column), f"Asylum-related grants in {column}"
        )
        resettlement = numeric(
            value_for(grant_table, "Resettlement arrivals", column), f"Resettlement arrivals in {column}"
        )
        total = numeric(value_for(grant_table, "Total", column), f"total grants and arrivals in {column}")
        expected_difference = -1 if column == "2024" else 0
        if grants != published_grants or grants + resettlement - total != expected_difference:
            raise ValueError(f"Asy_02a grant components do not reconcile in {column}.")

    children_table = tables["Asy_02b"]
    for column in periods:
        children_decisions = numeric(
            value_for(children_table, "Children receiving initial decisions", column),
            f"children decisions in {column}",
        )
        children_outcomes = sum(
            numeric(value_for(children_table, label, column), f"{label} in {column}")
            for label in ("Children granted", "Children refused")
        )
        uasc_decisions = numeric(
            value_for(children_table, "UASC receiving initial decisions", column), f"UASC decisions in {column}"
        )
        uasc_grants = numeric(value_for(children_table, "UASC granted", column), f"UASC grants in {column}")
        uasc_refusals = numeric(value_for(children_table, "UASC refused", column), f"UASC refusals in {column}")
        uasc_rate = numeric(value_for(children_table, "UASC grant rate", column), f"UASC grant rate in {column}")
        if children_outcomes != children_decisions or uasc_grants + uasc_refusals != uasc_decisions:
            raise ValueError(f"Asy_02b decision outcomes do not reconcile in {column}.")
        if not math.isclose(uasc_rate, uasc_grants / uasc_decisions, rel_tol=1e-12):
            raise ValueError(f"Asy_02b UASC grant rate does not match substantive decisions in {column}.")

    assessments = tables["Asy_05"]
    for column in periods:
        closed = numeric(value_for(assessments, "Closed", column), f"closed age assessments in {column}")
        age_results = sum(
            numeric(value_for(assessments, label, column), f"{label} assessments in {column}")
            for label in ("17 and under", "18 and over")
        )
        if closed != age_results:
            raise ValueError(f"Asy_05 age-assessment results do not reconcile in {column}.")

    inadmissibility = tables["Asy_02e"]
    inadmissibility_quarters = [
        f"{year} Q{quarter}"
        for year in range(2021, 2027)
        for quarter in range(1, (3 if year == 2026 else 5))
    ]
    if [column for column in inadmissibility["columns"] if re.fullmatch(r"20\d{2} Q[1-4]", column)] != inadmissibility_quarters:
        raise ValueError("Asy_02e must include quarterly observations from 2021 Q1 through 2026 Q2.")
    for label in INADMISSIBILITY_ROWS.values():
        row_total = sum(
            inadmissibility_count(inadmissibility, label, quarter) for quarter in inadmissibility_quarters
        )
        if row_total != inadmissibility_count(inadmissibility, label, "Total"):
            raise ValueError(f"Asy_02e quarterly values do not reconcile for {label}.")

    small_boat_rates = tables["Asy_02d"]
    for label in ("Grant rate - year ending June 2025 (cases)", "Grant rate - year ending June 2026 (cases)"):
        total = numeric(value_for(small_boat_rates, "All nationalities", label), label)
        if not 0 <= total <= 1:
            raise ValueError(f"{label} must be a case-based proportion.")


def annual_rows(tables):
    table = tables["Asy_00a"]
    labels = {
        "people_claiming_asylum": "People claiming asylum",
        "people_receiving_initial_decisions": "People receiving initial decisions",
        "grants_of_protection_or_other_leave": "Grants of protection or other leave",
        "refusals": "Refusals",
        "grant_rate_at_initial_decision": "Grant rate at initial decision",
        "people_awaiting_initial_decision": "People awaiting an initial decision",
        "cases_awaiting_initial_decision": "Cases awaiting an initial decision",
        "people_in_receipt_of_support": "Asylum seekers in receipt of support",
        "accommodated_in_hotels": "Of which accommodated in hotels",
        "asylum_related_returns": "Asylum-related returns",
        "enforced_returns": "Enforced",
        "voluntary_returns": "Voluntary",
    }
    result = []
    for year in range(2010, 2026):
        column = str(year)
        result.append({"year": year, **{
            key: optional_value(table, label, column)
            for key, label in labels.items()
        }})
    return result


def latest_summary(tables):
    flows = tables["Asy_00a"]
    column = "Year ending June 2026"
    labels = {
        "people_claiming_asylum": "People claiming asylum",
        "people_receiving_initial_decisions": "People receiving initial decisions",
        "grants_of_protection_or_other_leave": "Grants of protection or other leave",
        "refusals": "Refusals",
        "withdrawals": "Withdrawals",
        "published_initial_grant_rate_main_applicants": "Grant rate at initial decision",
        "people_awaiting_initial_decision": "People awaiting an initial decision",
        "cases_awaiting_initial_decision": "Cases awaiting an initial decision",
        "people_in_receipt_of_support": "Asylum seekers in receipt of support",
        "accommodated_in_hotels": "Of which accommodated in hotels",
        "asylum_related_returns": "Asylum-related returns",
        "enforced_returns": "Enforced",
        "voluntary_returns": "Voluntary",
    }
    return {key: optional_value(flows, label, column) for key, label in labels.items()}


def inadmissibility_series(tables):
    table = tables["Asy_02e"]
    quarters = [column for column in table["columns"] if re.fullmatch(r"20\d{2} Q[1-4]", column)]
    records = [
        {
            "quarter": quarter,
            **{
                key: inadmissibility_count(table, label, quarter)
                for key, label in INADMISSIBILITY_ROWS.items()
            },
        }
        for quarter in quarters
    ]
    result = pd.DataFrame(records)
    for key in INADMISSIBILITY_ROWS:
        result[f"cumulative_{key}"] = result[key].cumsum()
    return result


def make_headlines(metadata, tables, quarterly, work_in_progress, support):
    small_boat = tables["Asy_02d"]
    nationality_table = tables["Asy_01b"]
    nationality_latest = "Year ending June 2026"
    top_nationality = max(
        (row for row in nationality_table["rows"] if row["label"] not in {"Other", "Total"}),
        key=lambda row: row["values"][nationality_latest],
    )
    age_table = tables["Asy_01a"]
    route_table = tables["Asy_01c"]
    route_total = value_for(route_table, "Total", nationality_latest)
    small_boat_people = value_for(route_table, "Small Boat", nationality_latest)
    visa_people = value_for(route_table, "Visas and Other Leave", nationality_latest)
    quarter_flows = quarterly_flows_with_rolling_returns(quarterly)
    latest_quarter = quarter_flows.iloc[-1]
    latest_work_in_progress = work_in_progress.iloc[-1]
    latest_wip_stages = work_in_progress_stages(work_in_progress).iloc[-1]
    june_2024_pending = quarterly.loc[quarterly["quarter"] == "2024 Q2"].iloc[0]
    june_2024_wip = work_in_progress.loc[work_in_progress["Quarter"] == "2024 Q2"].iloc[0]
    june_2026_pending = quarterly.loc[quarterly["quarter"] == "2026 Q2"].iloc[0]
    inadmissibility = inadmissibility_series(tables)
    inadmissibility_totals = inadmissibility.iloc[-1]
    inadmissibility_identified = int(inadmissibility_totals["cumulative_identified"])
    accommodations = support_series(support)
    hotel_series = accommodations.dropna(subset=["hotel"])
    peak_hotel = hotel_series.loc[hotel_series["hotel"].idxmax()]
    latest_hotel = hotel_series.iloc[-1]
    latest_regions = hotel_region_breakdown(support).loc[lambda data: data["quarter"] == latest_hotel["quarter"]]
    largest_region = latest_regions.loc[latest_regions["people"].idxmax()]
    latest = "Year ending June 2026"
    decisions = quarterly.tail(4)
    decision_table = tables["Asy_00a"]
    grant_types = tables["Asy_02a"]
    children_table = tables["Asy_02b"]
    assessments = tables["Asy_05"]
    return {
        "source": metadata,
        "release": "Year ending June 2026",
        "published": "2026-08-27",
        "calendar_2025": {
            "people_claiming_asylum": value_for(tables["Asy_00a"], "People claiming asylum", "2025"),
            "published_initial_grant_rate_main_applicants": value_for(tables["Asy_00a"], "Grant rate at initial decision", "2025"),
        },
        "year_ending_june_2026": latest_summary(tables),
        "small_boat_case_grant_rates": {
            "year_ending_june_2025": value_for(small_boat, "All nationalities", "Grant rate - year ending June 2025 (cases)"),
            "year_ending_june_2026": value_for(small_boat, "All nationalities", "Grant rate - year ending June 2026 (cases)"),
        },
        "who_claims": {
            "top_nationality": top_nationality["label"],
            "top_nationality_people": top_nationality["values"][nationality_latest],
            "uasc_people": value_for(age_table, "Unaccompanied asylum-seeking children (UASC)", nationality_latest),
            "small_boat_people": small_boat_people,
            "small_boat_share": small_boat_people / route_total,
            "visas_and_other_leave_people": visa_people,
            "visas_and_other_leave_share": visa_people / route_total,
        },
        "decisions": {
            "claims": int(decisions["claims"].sum()),
            "substantive_decisions": int(decisions["substantive_decisions"].sum()),
            "grants": int(decisions["grants"].sum()),
            "refusals": int(decisions["refusals"].sum()),
            "withdrawals": int(decisions["withdrawals"].sum()),
            "administrative_outcomes": int(decisions["admin_outcomes"].sum()),
            "asylum_related_grants": value_for(grant_types, "Asylum-related grants", latest),
            "resettlement_arrivals": value_for(grant_types, "Resettlement arrivals", latest),
            "total_grants_and_arrivals": value_for(grant_types, "Total", latest),
            "published_initial_decisions": value_for(decision_table, "People receiving initial decisions", latest),
        },
        "children": {
            "children_decisions": value_for(children_table, "Children receiving initial decisions", latest),
            "children_granted": value_for(children_table, "Children granted", latest),
            "children_refused": value_for(children_table, "Children refused", latest),
            "uasc_decisions": value_for(children_table, "UASC receiving initial decisions", latest),
            "uasc_granted": value_for(children_table, "UASC granted", latest),
            "uasc_refused": value_for(children_table, "UASC refused", latest),
            "uasc_grant_rate": value_for(children_table, "UASC grant rate", latest),
            "age_assessments_raised": value_for(assessments, "Raised", latest),
            "age_assessments_closed": value_for(assessments, "Closed", latest),
            "age_assessments_17_and_under": value_for(assessments, "17 and under", latest),
            "age_assessments_18_and_over": value_for(assessments, "18 and over", latest),
        },
        "returns_and_stock": {
            "latest_quarter": latest_quarter["quarter"],
            "quarterly_claims": int(latest_quarter["claims"]),
            "quarterly_substantive_decisions": int(latest_quarter["substantive_decisions"]),
            "quarterly_asylum_related_returns": int(latest_quarter["asylum_related_returns"]),
            "rolling_12_month_asylum_related_returns": int(latest_quarter["rolling_12m_returns"]),
            "people_awaiting_initial_decision": int(latest_quarter["people_awaiting_initial_decision"]),
            "total_work_in_progress_cases": int(latest_work_in_progress["Total Work In Progress"]),
            "work_in_progress_quarter": latest_work_in_progress["Quarter"],
        },
        "work_in_progress": {
            "latest_quarter": latest_wip_stages["Quarter"],
            "total_cases": int(latest_wip_stages["Total Work In Progress"]),
            "awaiting_initial_decision_cases": int(latest_wip_stages["Awaiting Initial Asylum Decision"]),
            "awaiting_initial_decision_share": float(
                latest_wip_stages["Awaiting Initial Asylum Decision"]
                / latest_wip_stages["Total Work In Progress"]
            ),
            "not_awaiting_initial_decision_cases": int(latest_wip_stages["not_awaiting"]),
            "not_awaiting_initial_decision_share": float(latest_wip_stages["not_awaiting_share"]),
        },
        "awaiting_comparison": {
            "june_2024": {
                "people": int(june_2024_pending["people_awaiting_initial_decision"]),
                "main_applicant_cases": int(june_2024_pending["main_applicants_awaiting_initial_decision"]),
                "dependants": int(
                    june_2024_pending["people_awaiting_initial_decision"]
                    - june_2024_pending["main_applicants_awaiting_initial_decision"]
                ),
                "wip_awaiting_cases": int(june_2024_wip["Awaiting Initial Asylum Decision"]),
                "wip_total_cases": int(june_2024_wip["Total Work In Progress"]),
                "publication_difference_cases": abs(
                    int(june_2024_wip["Awaiting Initial Asylum Decision"])
                    - int(june_2024_pending["main_applicants_awaiting_initial_decision"])
                ),
            },
            "june_2026": {
                "people": int(june_2026_pending["people_awaiting_initial_decision"]),
                "main_applicant_cases": int(
                    june_2026_pending["main_applicants_awaiting_initial_decision"]
                ),
                "dependants": int(
                    june_2026_pending["people_awaiting_initial_decision"]
                    - june_2026_pending["main_applicants_awaiting_initial_decision"]
                ),
            },
        },
        "inadmissibility": {
            "period": "2021 Q1 to 2026 Q2",
            "identified": inadmissibility_identified,
            "notices_of_intent": int(inadmissibility_totals["cumulative_notices_of_intent"]),
            "decisions_served": int(inadmissibility_totals["cumulative_decisions_served"]),
            "removals": int(inadmissibility_totals["cumulative_removals"]),
            "subsequently_admitted": int(inadmissibility_totals["cumulative_subsequently_admitted"]),
            "admitted_to_identified_event_ratio": (
                int(inadmissibility_totals["cumulative_subsequently_admitted"]) / inadmissibility_identified
            ),
            "removals_to_identified_event_ratio": (
                int(inadmissibility_totals["cumulative_removals"]) / inadmissibility_identified
            ),
            "latest_quarter": inadmissibility.iloc[-1]["quarter"],
            "latest_identified": int(inadmissibility.iloc[-1]["identified"]),
            "latest_admitted": int(inadmissibility.iloc[-1]["subsequently_admitted"]),
            "latest_removals": int(inadmissibility.iloc[-1]["removals"]),
        },
        "hotel_accommodation": {
            "peak_quarter": peak_hotel["quarter"],
            "peak_people": int(peak_hotel["hotel"]),
            "latest_quarter": latest_hotel["quarter"],
            "latest_people": int(latest_hotel["hotel"]),
            "latest_total_supported": int(latest_hotel["total_supported"]),
            "largest_region_latest": largest_region["uk_region"],
            "largest_region_latest_people": int(largest_region["people"]),
        },
    }


def style_axis(ax):
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="both", colors=MUTED, labelsize=9, length=0, pad=7)
    ax.grid(axis="y", color=GRID, linewidth=.8)
    ax.set_axisbelow(True)


def format_count(value, max_value):
    if value == 0:
        return "0"
    if max_value >= COUNT_AXIS_K_THRESHOLD:
        label = f"{value / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{label}K"
    return f"{value:,.0f}"


def format_count_axis(axis, max_value):
    axis.set_major_formatter(plt.FuncFormatter(lambda value, _: format_count(value, max_value)))


def save_chart(fig, name):
    ASSETS.mkdir(parents=True, exist_ok=True)
    path = ASSETS / f"{name}.svg"
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    svg = path.read_text(encoding="utf-8")
    path.write_text("\n".join(line.rstrip() for line in svg.splitlines()) + "\n", encoding="utf-8")


LEGEND_BORDER_PAD = 1.8


def add_legend(fig, ax, ncol, fontsize=9, additional_axes=()):
    handles, labels = ax.get_legend_handles_labels()
    for additional_ax in additional_axes:
        extra_handles, extra_labels = additional_ax.get_legend_handles_labels()
        handles.extend(extra_handles)
        labels.extend(extra_labels)
    fig.legend(
        handles, labels, loc="outside lower center", ncol=ncol,
        frameon=False, fontsize=fontsize, borderpad=LEGEND_BORDER_PAD,
    )


def chart_claims_by_nationality(tables):
    table = tables["Asy_01b"]
    prior_column = "Year ending June 2025"
    latest_column = "Year ending June 2026"
    rows = [row for row in table["rows"] if row["label"] not in {"Other", "Total"}]
    rows = sorted(rows, key=lambda row: row["values"][latest_column], reverse=True)[:20]
    rows.sort(key=lambda row: row["values"][latest_column])
    labels = [row["label"] for row in rows]
    prior = [row["values"][prior_column] for row in rows]
    latest = [row["values"][latest_column] for row in rows]
    fig, ax = plt.subplots(figsize=(10.5, 7.8), layout="constrained")
    positions = list(range(len(labels)))
    ax.barh([position + .17 for position in positions], prior, height=.32,
            color="#b9c9bf", label="Year ending June 2025")
    ax.barh([position - .17 for position in positions], latest, height=.32,
            color=TEAL, label="Year ending June 2026")
    ax.set_yticks(positions, labels)
    ax.set_xlim(left=0)
    ax.set_xlabel("People claiming asylum", color=MUTED)
    format_count_axis(ax.xaxis, max([*prior, *latest]))
    ax.set_title("Claims by nationality", loc="left", color=INK, fontsize=15, pad=14)
    ax.grid(axis="x", color=GRID, linewidth=.8)
    ax.yaxis.grid(False)
    ax.spines[["top", "right", "left", "bottom"]].set_visible(False)
    ax.tick_params(axis="both", colors=MUTED, labelsize=8.5, length=0, pad=6)
    add_legend(fig, ax, ncol=2)
    save_chart(fig, "claims-by-nationality")


def chart_claims_by_age(tables):
    table = tables["Asy_01a"]
    age_rows = age_group_rows(table, "Total people")
    years = list(range(2010, 2026))
    categories = ["13 and under", "14 to 15", "16 to 17", "18 and over"]
    colors = ["#80a99b", GOLD, PURPLE, TEAL]
    positions = list(range(len(years)))
    fig, ax = plt.subplots(figsize=(10.5, 5), layout="constrained")
    bottom = [0] * len(years)
    for label, color in zip(categories, colors):
        values = [age_rows[label]["values"][str(year)] for year in years]
        ax.bar(positions, values, bottom=bottom, color=color, width=.72, label=label)
        bottom = [current + value for current, value in zip(bottom, values)]
    uasc = [value_for(table, "Unaccompanied asylum-seeking children (UASC)", str(year))
            for year in years]
    ax.plot(positions, uasc, color="#b95f4b", linewidth=2.2, marker="o", markersize=3.5,
            label="UASC (subset of children)")
    ax.set_xticks(positions, [str(year) for year in years])
    ax.set_xlim(-.6, len(years) - .4)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("People claiming asylum", color=MUTED)
    format_count_axis(ax.yaxis, max(bottom))
    ax.set_title("Age profile of asylum claims", loc="left", color=INK, fontsize=15, pad=14)
    style_axis(ax)
    add_legend(fig, ax, ncol=3, fontsize=8.5)
    save_chart(fig, "claims-by-age")


def chart_claims_by_route(tables):
    table = tables["Asy_01c"]
    years = list(range(2018, 2026))
    categories = [
        ("Small Boat", TEAL, "Small boat"),
        ("Clandestine", GOLD, "Clandestine"),
        ("Entered Without Relevant Documentation", PURPLE, "No relevant documentation"),
        ("Visas and Other Leave", "#80a99b", "Visas / other leave"),
        ("Other", MUTED, "Other"),
    ]
    positions = list(range(len(years)))
    fig, ax = plt.subplots(figsize=(10.5, 5), layout="constrained")
    bottom = [0] * len(years)
    for label, color, legend_label in categories:
        values = [value_for(table, label, str(year)) for year in years]
        ax.bar(positions, values, bottom=bottom, color=color, width=.7, label=legend_label)
        bottom = [current + value for current, value in zip(bottom, values)]
    ax.set_xticks(positions, [str(year) for year in years])
    ax.set_xlim(-.6, len(years) - .4)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("People claiming asylum", color=MUTED)
    format_count_axis(ax.yaxis, max(bottom))
    ax.set_title("Claims by route before claiming", loc="left", color=INK, fontsize=15, pad=14)
    style_axis(ax)
    add_legend(fig, ax, ncol=3, fontsize=8.5)
    save_chart(fig, "claims-by-route")


def chart_nationality_routes(tables):
    table = tables["Asy_01d"]
    route_columns = [
        ("Small Boat", TEAL, "Small boat"),
        ("Clandestine", GOLD, "Clandestine"),
        ("Entered Without Relevant Documentation", PURPLE, "No relevant documentation"),
        ("Visas and Other Leave", "#80a99b", "Visas / other leave"),
        ("Other", MUTED, "Other"),
    ]
    nationalities = [row for row in table["rows"] if row["label"] not in {"Other", "Total"}]
    top_nationalities = sorted(nationalities, key=lambda row: row["values"]["Total"], reverse=True)[:12]
    top_nationalities.sort(key=lambda row: row["values"]["Total"])
    all_nationalities = dict(row_for(table, "Total"), label="All nationalities")
    rows = [all_nationalities, *top_nationalities]
    labels = [row["label"] for row in rows]
    totals = [row["values"]["Total"] for row in rows]
    fig, ax = plt.subplots(figsize=(10.8, 6.7), layout="constrained")
    positions = list(range(len(labels)))
    left = [0.0] * len(labels)
    for column, color, legend_label in route_columns:
        values = [row["values"][column] / total for row, total in zip(rows, totals)]
        ax.barh(positions, values, left=left, color=color, height=.68, label=legend_label)
        left = [current + value for current, value in zip(left, values)]
    ax.set_yticks(positions, labels)
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"{value:.0%}"))
    ax.set_xlabel("Share of claims", color=MUTED)
    ax.set_title("Prior route by nationality", loc="left", color=INK, fontsize=15, pad=14)
    ax.grid(axis="x", color=GRID, linewidth=.8)
    ax.yaxis.grid(False)
    ax.spines[["top", "right", "left", "bottom"]].set_visible(False)
    ax.tick_params(axis="both", colors=MUTED, labelsize=8.5, length=0, pad=6)
    add_legend(fig, ax, ncol=3, fontsize=8.5)
    save_chart(fig, "nationality-routes")


def chart_grant_types(tables):
    table = tables["Asy_02a"]
    years = list(range(2010, 2026))
    categories = [
        ("Refugee Permission", TEAL, "Refugee permission"),
        ("Temporary Refugee Permission", "#80a99b", "Temporary refugee permission"),
        ("Humanitarian Protection", PURPLE, "Humanitarian protection"),
        ("Discretionary Leave", GOLD, "Discretionary leave"),
        ("UASC Leave", "#b95f4b", "UASC leave"),
        ("Other Grants", MUTED, "Other grants"),
    ]
    positions = list(range(len(years)))
    fig, ax = plt.subplots(figsize=(11, 5.2), layout="constrained")
    bottom = [0] * len(years)
    for label, color, legend_label in categories:
        values = [value_for(table, label, str(year)) or 0 for year in years]
        ax.bar(positions, values, bottom=bottom, color=color, width=.72, label=legend_label)
        bottom = [current + value for current, value in zip(bottom, values)]
    resettlement = [value_for(table, "Resettlement arrivals", str(year)) for year in years]
    ax.plot(positions, resettlement, color=INK, linewidth=1.8, marker="o", markersize=3,
            linestyle="--", label="Resettlement arrivals (not a decision)")
    ax.set_xticks(positions, [str(year) for year in years])
    ax.set_xlim(-.6, len(years) - .4)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("People", color=MUTED)
    format_count_axis(ax.yaxis, max(max(bottom), max(resettlement)))
    ax.set_title("Asylum-related grants by type", loc="left", color=INK, fontsize=15, pad=14)
    style_axis(ax)
    add_legend(fig, ax, ncol=4, fontsize=8)
    save_chart(fig, "grant-types")


def chart_children_decisions(tables):
    table = tables["Asy_02b"]
    years = list(range(2010, 2026))
    granted = [value_for(table, "Children granted", str(year)) for year in years]
    refused = [value_for(table, "Children refused", str(year)) for year in years]
    uasc = [value_for(table, "UASC receiving initial decisions", str(year)) for year in years]
    positions = list(range(len(years)))
    fig, ax = plt.subplots(figsize=(10.5, 5), layout="constrained")
    ax.bar(positions, granted, color=TEAL, width=.72, label="Children granted")
    ax.bar(positions, refused, bottom=granted, color=GOLD, width=.72, label="Children refused")
    ax.plot(positions, uasc, color="#b95f4b", linewidth=2.2, marker="o", markersize=3.5,
            label="UASC decisions (subset)")
    totals = [grant + refusal for grant, refusal in zip(granted, refused)]
    ax.set_xticks(positions, [str(year) for year in years])
    ax.set_xlim(-.6, len(years) - .4)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("People receiving initial decisions", color=MUTED)
    format_count_axis(ax.yaxis, max(totals))
    ax.set_title("Initial decisions involving children", loc="left", color=INK, fontsize=15, pad=14)
    style_axis(ax)
    add_legend(fig, ax, ncol=3, fontsize=8.5)
    save_chart(fig, "children-decisions")


def chart_uasc_grant_rate(tables):
    uasc_table = tables["Asy_02b"]
    main_table = tables["Asy_00a"]
    years = list(range(2010, 2026))
    uasc = [value_for(uasc_table, "UASC grant rate", str(year)) for year in years]
    main_applicants = [value_for(main_table, "Grant rate at initial decision", str(year)) for year in years]
    fig, ax = plt.subplots(figsize=(10.5, 4.6), layout="constrained")
    ax.plot(years, uasc, color=PURPLE, linewidth=2.4, marker="o", markersize=3,
            label="UASC substantive grant rate")
    ax.plot(years, main_applicants, color=TEAL, linewidth=2.4, marker="o", markersize=3,
            label="Main-applicant substantive grant rate")
    ax.set_xticks([2010, 2015, 2020, 2025])
    ax.set_xlim(2009.5, 2025.5)
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"{value:.0%}"))
    ax.set_ylabel("Share of substantive decisions", color=MUTED)
    ax.set_title("Initial grant rates: UASC and main applicants", loc="left", color=INK, fontsize=15, pad=14)
    style_axis(ax)
    add_legend(fig, ax, ncol=2)
    save_chart(fig, "uasc-grant-rate")


def chart_age_assessments(tables):
    table = tables["Asy_05"]
    years = list(range(2010, 2026))
    under_18 = [value_for(table, "17 and under", str(year)) for year in years]
    adults = [value_for(table, "18 and over", str(year)) for year in years]
    raised = [value_for(table, "Raised", str(year)) for year in years]
    positions = list(range(len(years)))
    fig, ax = plt.subplots(figsize=(10.5, 5), layout="constrained")
    ax.bar(positions, under_18, color=TEAL, width=.72, label="Closed: assessed 17 and under")
    ax.bar(positions, adults, bottom=under_18, color=GOLD, width=.72,
           label="Closed: assessed 18 and over")
    ax.plot(positions, raised, color=PURPLE, linewidth=2.2, marker="o", markersize=3.5,
            label="Assessments raised")
    closed = [under + adult for under, adult in zip(under_18, adults)]
    ax.set_xticks(positions, [str(year) for year in years])
    ax.set_xlim(-.6, len(years) - .4)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("People subject to age assessment", color=MUTED)
    format_count_axis(ax.yaxis, max(max(closed), max(raised)))
    ax.set_title("Age assessments raised and closed", loc="left", color=INK, fontsize=15, pad=14)
    style_axis(ax)
    add_legend(fig, ax, ncol=3, fontsize=8.5)
    save_chart(fig, "age-assessments")


def chart_annual_flows(tables):
    table = tables["Asy_00a"]
    years = list(range(2010, 2026))
    fig, ax = plt.subplots(figsize=(10.5, 4.7), layout="constrained")
    all_values = []
    for label, colour, row in [
        ("People claiming asylum", TEAL, "People claiming asylum"),
        ("People receiving initial decisions", GOLD, "People receiving initial decisions"),
    ]:
        values = [value_for(table, row, str(year)) for year in years]
        all_values.extend(values)
        ax.plot(years, values, color=colour, linewidth=2.6, marker="o", markersize=3, label=label)
    ax.set_xticks([2010, 2015, 2020, 2025])
    ax.set_xlim(2009.5, 2025.5)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("People", color=MUTED)
    format_count_axis(ax.yaxis, max(all_values))
    ax.set_title("Asylum claims and initial decisions", loc="left", color=INK, fontsize=15, pad=14)
    style_axis(ax)
    add_legend(fig, ax, ncol=2)
    save_chart(fig, "annual-claims-decisions")


def chart_grant_rates(tables):
    table = tables["Asy_00a"]
    years = list(range(2010, 2026))
    values = [value_for(table, "Grant rate at initial decision", str(year)) for year in years]
    fig, ax = plt.subplots(figsize=(10.5, 4.4), layout="constrained")
    ax.plot(years, values, color=TEAL, linewidth=2.8, marker="o", markersize=3)
    ax.set_xticks([2010, 2015, 2020, 2025])
    ax.set_xlim(2009.5, 2025.5)
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"{value:.0%}"))
    ax.set_title("Published initial grant rate", loc="left", color=INK, fontsize=15, pad=14)
    ax.set_ylabel("Share of substantive initial decisions (main applicants)", color=MUTED)
    style_axis(ax)
    save_chart(fig, "initial-grant-rates")


def chart_small_boat_rates(tables):
    table = tables["Asy_02d"]
    old_column = "Grant rate - year ending June 2025 (cases)"
    new_column = "Grant rate - year ending June 2026 (cases)"
    rows = [row for row in table["rows"] if row["label"] != "All nationalities"]
    rows = [row for row in rows if isinstance(row["values"].get(new_column), (int, float))]
    rows.sort(key=lambda row: row["values"][new_column])
    labels = [row["label"] for row in rows]
    prior = [row["values"][old_column] for row in rows]
    latest = [row["values"][new_column] for row in rows]
    fig, ax = plt.subplots(figsize=(9.5, 5.3), layout="constrained")
    positions = list(range(len(labels)))
    ax.barh([position + .17 for position in positions], prior, height=.32, color="#b9c9bf", label="Year ending June 2025")
    ax.barh([position - .17 for position in positions], latest, height=.32, color=TEAL, label="Year ending June 2026")
    ax.set_yticks(positions, labels)
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"{value:.0%}"))
    ax.set_xlabel("Case-based grant rate", color=MUTED)
    ax.set_title("Small-boat claims: published case grant rates", loc="left", color=INK, fontsize=15, pad=14)
    ax.grid(axis="x", color=GRID, linewidth=.8)
    ax.yaxis.grid(False)
    ax.spines[["top", "right", "left", "bottom"]].set_visible(False)
    ax.tick_params(axis="both", colors=MUTED, labelsize=9, length=0, pad=6)
    add_legend(fig, ax, ncol=2)
    save_chart(fig, "small-boat-grant-rates")


def chart_inadmissibility_quarterly(tables):
    data = inadmissibility_series(tables)
    dates = quarter_end_dates(data["quarter"])
    fig, ax = plt.subplots(figsize=(11, 5), layout="constrained")
    ax.plot(dates, data["identified"], color=TEAL, linewidth=2.3, marker="o", markersize=3,
            label="Identified for consideration")
    ax.plot(dates, data["notices_of_intent"], color=GOLD, linewidth=2.1, marker="o", markersize=3,
            label="Notice of intent issued")
    ax.plot(dates, data["subsequently_admitted"], color=PURPLE, linewidth=2.3, marker="o", markersize=3,
            label="Subsequently admitted to asylum process")

    event_ax = ax.twinx()
    event_ax.patch.set_visible(False)
    event_ax.bar(dates - pd.Timedelta(days=11), data["decisions_served"], width=17,
                 color="#b9c9bf", label="Inadmissibility decision served")
    event_ax.bar(dates + pd.Timedelta(days=11), data["removals"], width=17,
                 color="#8d7770", label="Removals")
    event_max = max(data["decisions_served"].max(), data["removals"].max())
    event_ax.set_ylim(0, event_max * 1.15)
    format_count_axis(event_ax.yaxis, event_max)
    event_ax.set_ylabel("Decisions served or removals", color=MUTED)
    event_ax.tick_params(axis="y", colors=MUTED, labelsize=9, length=0, pad=7)
    event_ax.spines[["top", "left", "bottom"]].set_visible(False)
    event_ax.spines["right"].set_color(GRID)
    event_ax.grid(False)

    ax.set_ylim(bottom=0)
    ax.set_ylabel("People identified, notified or subsequently admitted", color=MUTED)
    format_count_axis(ax.yaxis, max(data["identified"].max(), data["notices_of_intent"].max(),
                                    data["subsequently_admitted"].max()))
    ax.set_title("Inadmissibility-related events by quarter", loc="left", color=INK, fontsize=15, pad=14)
    style_quarter_axis(ax, "2021-01-01", "2026-06-30")
    years = list(range(2021, 2027))
    ax.set_xticks([pd.Timestamp(year=year, month=1, day=1) for year in years], [str(year) for year in years])
    ax.set_xlabel("Quarter", color=MUTED)
    add_legend(fig, ax, ncol=3, fontsize=8.5, additional_axes=(event_ax,))
    save_chart(fig, "inadmissibility-quarterly")


def quarter_end_dates(quarters):
    quarters = pd.Series(quarters)
    quarter_number = quarters.str[-1].astype(int)
    return pd.to_datetime({
        "year": quarters.str[:4].astype(int),
        "month": quarter_number * 3,
        "day": 1,
    }) + pd.offsets.MonthEnd(0)


def chart_inadmissibility_totals(tables):
    data = inadmissibility_series(tables)
    rows = [
        ("Identified for consideration", "cumulative_identified", MUTED),
        ("Notice of intent issued", "cumulative_notices_of_intent", GOLD),
        ("Inadmissibility decision served", "cumulative_decisions_served", "#b9c9bf"),
        ("Removals", "cumulative_removals", "#8d7770"),
        ("Subsequently admitted to asylum process", "cumulative_subsequently_admitted", TEAL),
    ]
    labels = [label for label, _, _ in rows]
    values = [int(data.iloc[-1][column]) for _, column, _ in rows]
    colors = [color for _, _, color in rows]
    positions = list(range(len(rows)))
    maximum = max(values)
    fig, ax = plt.subplots(figsize=(10.5, 4.5), layout="constrained")
    ax.barh(positions, values, color=colors, height=.62)
    for position, value in zip(positions, values):
        ax.text(value + maximum * .012, position, f"{value:,}", va="center", ha="left", fontsize=9, color=INK)
    ax.set_yticks(positions, labels)
    ax.invert_yaxis()
    ax.set_xlim(0, maximum * 1.17)
    ax.set_xlabel("Published events, 2021 Q1 to 2026 Q2", color=MUTED)
    format_count_axis(ax.xaxis, maximum)
    ax.set_title("Inadmissibility-related event totals", loc="left", color=INK, fontsize=15, pad=14)
    ax.xaxis.grid(True, color=GRID, linewidth=.8)
    ax.yaxis.grid(False)
    ax.spines[["top", "right", "left", "bottom"]].set_visible(False)
    ax.tick_params(axis="both", colors=MUTED, labelsize=9, length=0, pad=7)
    ax.set_axisbelow(True)
    save_chart(fig, "inadmissibility-totals")


def chart_waiting_times(tables):
    table = tables["Asy_03a"]
    date_columns = [column for column in table["columns"] if column.startswith("Year ending June")]
    if not date_columns:
        date_columns = [column for column in table["columns"] if re.fullmatch(r"20\d{2}", column)]
    if not date_columns:
        raise ValueError("Asy_03a has no dated columns for its waiting-time chart.")
    latest_column = date_columns[-1]
    categories = ["Less than 3 months", "3 months to less than 6 months", "6 months to less than 12 months", "12 months or more"]
    values = [numeric(value_for(table, label, latest_column), f"{label} in {latest_column}") for label in categories]
    fig, ax = plt.subplots(figsize=(9.2, 3.5), layout="constrained")
    left = 0
    colors = [TEAL, "#80a99b", GOLD, "#b95f4b"]
    for label, value, color in zip(categories, values, colors):
        ax.barh([0], [value], left=[left], color=color, height=.48, label=label)
        left += value
    ax.set_yticks([])
    ax.set_xlabel("People awaiting an initial decision", color=MUTED)
    format_count_axis(ax.xaxis, sum(values))
    ax.set_title(f"Initial-decision waiting time at {latest_column}", loc="left", color=INK, fontsize=15, pad=14)
    ax.xaxis.grid(True, color=GRID, linewidth=.8)
    ax.yaxis.grid(False)
    ax.spines[["top", "right", "left", "bottom"]].set_visible(False)
    ax.tick_params(axis="x", colors=MUTED, labelsize=9, length=0, pad=7)
    add_legend(fig, ax, ncol=2, fontsize=8)
    save_chart(fig, "waiting-times")


def chart_support(tables):
    table = tables["Asy_09b"]
    columns = [column for column in table["columns"] if re.fullmatch(r"(?:Dec|Jun) 20\d{2}", column)]
    values = [optional_value(table, "Total in receipt of support", column) for column in columns]
    pairs = [(column, value) for column, value in zip(columns, values) if isinstance(value, (int, float))]
    if not pairs:
        raise ValueError("Asy_09b has no dated total-support observations.")
    fig, ax = plt.subplots(figsize=(10.5, 4.2), layout="constrained")
    ax.plot(range(len(pairs)), [value for _, value in pairs], color=PURPLE, linewidth=2.8, marker="o", markersize=3)
    ticks = list(range(0, len(pairs), max(1, len(pairs) // 6)))
    if ticks[-1] != len(pairs) - 1:
        ticks.append(len(pairs) - 1)
    ax.set_xticks(ticks, [pairs[index][0] for index in ticks], rotation=30, ha="right")
    ax.set_ylim(bottom=0)
    ax.set_ylabel("People", color=MUTED)
    format_count_axis(ax.yaxis, max(value for _, value in pairs))
    ax.set_title("People receiving asylum support", loc="left", color=INK, fontsize=15, pad=14)
    style_axis(ax)
    save_chart(fig, "asylum-support")


def chart_hotel_accommodation(support):
    data = support_series(support)
    dates = pd.to_datetime(data["period_end"])
    fig, ax = plt.subplots(figsize=(11, 4.8), layout="constrained")
    ax.plot(dates, data["total_supported"], color=MUTED, linewidth=1.8,
            label="All people receiving support")
    ax.plot(dates, data["section_98"], color=GOLD, linewidth=2.1, linestyle="--",
            label="Section 98 accommodation (not hotels)")
    ax.plot(dates, data["hotel"], color=TEAL, linewidth=2.7, marker="o", markersize=3,
            label="Contingency accommodation – hotels")
    hotel_start = pd.Timestamp("2022-12-31")
    ax.axvline(hotel_start, color=MUTED, linewidth=1.2, linestyle=":",
               label="Separate hotel count begins")
    ax.set_ylim(bottom=0)
    ax.set_ylabel("People receiving Home Office support", color=MUTED)
    format_count_axis(ax.yaxis, data["total_supported"].max())
    ax.set_title("Asylum support and hotel accommodation", loc="left", color=INK, fontsize=15, pad=14)
    style_quarter_axis(ax, "2014-03-31", "2026-06-30")
    years = [2014, 2018, 2022, 2026]
    ax.set_xticks([pd.Timestamp(year=year, month=1, day=1) for year in years], [str(year) for year in years])
    add_legend(fig, ax, ncol=2, fontsize=8.5)
    save_chart(fig, "hotel-accommodation")


def chart_hotel_regions(support):
    national = support_series(support)
    hotels = national.dropna(subset=["hotel"])
    peak = hotels.loc[hotels["hotel"].idxmax()]
    latest = hotels.iloc[-1]
    regions = hotel_region_breakdown(support)
    peak_regions = regions.loc[regions["quarter"] == peak["quarter"]].set_index("uk_region")["people"]
    latest_regions = regions.loc[regions["quarter"] == latest["quarter"]].set_index("uk_region")["people"]
    labels = sorted(
        set(peak_regions.index) | set(latest_regions.index),
        key=lambda label: max(peak_regions.get(label, 0), latest_regions.get(label, 0)),
    )
    peak_values = [int(peak_regions.get(label, 0)) for label in labels]
    latest_values = [int(latest_regions.get(label, 0)) for label in labels]
    positions = range(len(labels))
    fig, ax = plt.subplots(figsize=(10.5, 6.5), layout="constrained")
    ax.barh([position - .19 for position in positions], peak_values, height=.36, color=GOLD,
            label=f"{peak['quarter']} hotel peak")
    ax.barh([position + .19 for position in positions], latest_values, height=.36, color=TEAL,
            label=latest["quarter"])
    ax.set_yticks(list(positions), labels)
    ax.invert_yaxis()
    ax.set_xlabel("People in contingency hotel accommodation", color=MUTED)
    format_count_axis(ax.xaxis, max(peak_values + latest_values))
    ax.set_title("Hotel accommodation by UK region or nation", loc="left", color=INK, fontsize=15, pad=14)
    ax.xaxis.grid(True, color=GRID, linewidth=.8)
    ax.yaxis.grid(False)
    ax.spines[["top", "right", "left", "bottom"]].set_visible(False)
    ax.tick_params(axis="both", colors=MUTED, labelsize=9, length=0, pad=7)
    ax.set_axisbelow(True)
    add_legend(fig, ax, ncol=2)
    save_chart(fig, "hotel-by-region")


def style_quarter_axis(ax, start, end):
    years = list(range(2010, 2027, 4))
    ax.set_xticks([pd.Timestamp(year=year, month=1, day=1) for year in years])
    ax.set_xticklabels([str(year) for year in years])
    ax.set_xlim(pd.Timestamp(start), pd.Timestamp(end))
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="both", colors=MUTED, labelsize=9, length=0, pad=7)
    ax.grid(axis="y", color=GRID, linewidth=.8)
    ax.set_axisbelow(True)


def chart_quarterly_flows(quarterly):
    data = quarterly.copy()
    dates = pd.to_datetime(data["period_end"])
    fig, ax = plt.subplots(figsize=(11, 4.8), layout="constrained")
    ax.plot(dates, data["claims"], color=TEAL, linewidth=2.3, marker="o", markersize=2.5,
            label="People claiming asylum")
    ax.plot(dates, data["substantive_decisions"], color=GOLD, linewidth=2.3, marker="o", markersize=2.5,
            label="Substantive initial decisions")
    ax.plot(dates, data["asylum_related_returns"], color=PURPLE, linewidth=1.9, marker="o", markersize=2.2,
            label="Asylum-related returns")
    ax.set_ylim(bottom=0)
    ax.set_ylabel("People or recorded returns", color=MUTED)
    format_count_axis(ax.yaxis, max(data["claims"].max(), data["substantive_decisions"].max()))
    ax.set_title("Quarterly asylum claims, decisions and returns", loc="left", color=INK, fontsize=15, pad=14)
    style_quarter_axis(ax, "2010-01-01", "2026-06-30")
    add_legend(fig, ax, ncol=3)
    save_chart(fig, "quarterly-flows-returns")


def chart_quarterly_decision_outcomes(quarterly):
    data = quarterly.copy()
    dates = pd.to_datetime(data["period_end"])
    categories = [
        ("grants", TEAL, "Grants"),
        ("refusals", GOLD, "Refusals"),
        ("withdrawals", PURPLE, "Withdrawals"),
        ("admin_outcomes", MUTED, "Administrative outcomes"),
    ]
    fig, ax = plt.subplots(figsize=(11, 5), layout="constrained")
    bottom = [0] * len(data)
    for column, color, label in categories:
        values = data[column].astype(int).tolist()
        ax.bar(dates, values, width=68, bottom=bottom, color=color, label=label)
        bottom = [current + value for current, value in zip(bottom, values)]
    claims = data["claims"].tolist()
    ax.plot(dates, claims, color="#b95f4b", linewidth=2, marker="o", markersize=2.2,
            label="People claiming asylum")
    ax.set_ylim(bottom=0)
    format_count_axis(ax.yaxis, max(max(bottom), max(claims)))
    ax.set_ylabel("People", color=MUTED)
    ax.set_title("Quarterly claims and recorded initial outcomes", loc="left", color=INK, fontsize=15, pad=14)
    style_quarter_axis(ax, "2010-01-01", "2026-06-30")
    add_legend(fig, ax, ncol=3, fontsize=8.5)
    save_chart(fig, "quarterly-claims-outcomes")


def chart_work_in_progress_stages(work_in_progress):
    data = work_in_progress_stages(work_in_progress)
    positions = list(range(len(data)))
    bottom = [0] * len(data)
    categories = [
        ("Awaiting Initial Asylum Decision", TEAL, "Awaiting initial decision"),
        ("Post Decision", PURPLE, "Post-decision component"),
        ("Asylum Appeal Outstanding", "#80a99b", "Appeal outstanding"),
        ("Subject to Removal Action", GOLD, "Subject to removal action"),
        ("On Hold", MUTED, "On hold (decision status may vary)"),
        ("Further Leave Application Outstanding", "#b95f4b", "Further leave application"),
    ]
    fig, ax = plt.subplots(figsize=(11.5, 6), layout="constrained")
    undivided = (
        data["Post Decision"].notna()
        & data["decided_excluding_on_hold"].isna()
    )
    for column, color, label in categories:
        values = data[column].fillna(0).astype(int).tolist()
        if column == "Post Decision":
            values = [0 if is_undivided else value for value, is_undivided in zip(values, undivided)]
        kwargs = {"hatch": "///", "edgecolor": "white", "linewidth": .4} if column == "On Hold" else {}
        ax.bar(positions, values, bottom=bottom, color=color, width=.72, label=label, **kwargs)
        bottom = [current + value for current, value in zip(bottom, values)]

    undivided_values = [
        int(value) if is_undivided else 0
        for value, is_undivided in zip(data["Post Decision"].fillna(0), undivided)
    ]
    ax.bar(
        positions, undivided_values, bottom=bottom, color="#e7e2d9", edgecolor=GOLD,
        hatch="///", linewidth=.5, width=.72, label="2024 post-decision total (no breakdown)",
    )
    totals = data["Total Work In Progress"].astype(int).tolist()
    shares = data["not_awaiting_share"].tolist()
    for position, total, share in zip(positions, totals, shares):
        ax.text(position, total + max(totals) * .012, f"{share:.0%}", ha="center", va="bottom",
                fontsize=8, color=MUTED)

    ax.axvline(2.5, color=MUTED, linewidth=1.2, linestyle=":")
    ax.annotate(
        "2014 methodology break", xy=(2.5, .98), xycoords=("data", "axes fraction"),
        xytext=(5, -4), textcoords="offset points", rotation=90, ha="left", va="top",
        fontsize=8, color=MUTED,
    )
    ax.set_xticks(positions, data["Quarter"].str[:4])
    ax.set_xlim(-.6, len(data) - .4)
    ax.set_ylim(0, max(totals) * 1.12)
    ax.set_ylabel("Main-applicant cases", color=MUTED)
    format_count_axis(ax.yaxis, max(totals))
    ax.set_title("Work-in-progress cases by published stage", loc="left", color=INK, fontsize=15, pad=14)
    style_axis(ax)
    ax.tick_params(axis="x", labelsize=8, pad=6)
    add_legend(fig, ax, ncol=4, fontsize=7.8)
    save_chart(fig, "work-in-progress-stages")


def chart_stock_and_returns(quarterly, work_in_progress):
    data = quarterly_flows_with_rolling_returns(quarterly)
    stock = data.dropna(subset=["people_awaiting_initial_decision"])
    returns = data.dropna(subset=["rolling_12m_returns"])
    wip = work_in_progress.dropna(subset=["Total Work In Progress"])
    stock_dates = pd.to_datetime(stock["period_end"])
    return_dates = pd.to_datetime(returns["period_end"])
    wip_dates = pd.to_datetime(wip["period_end"])
    fig, ax = plt.subplots(figsize=(11, 4.8), layout="constrained")
    ax.plot(stock_dates, stock["people_awaiting_initial_decision"], color=TEAL, linewidth=2.5,
            label="Awaiting initial decision (people)")
    ax.plot(wip_dates, wip["Total Work In Progress"], color=GOLD, linewidth=2.2, marker="o",
            markersize=4, label="Total work in progress (main-applicant cases)")
    ax.plot(return_dates, returns["rolling_12m_returns"], color=PURPLE, linewidth=2.2,
            label="Asylum-related returns in previous 12 months")
    ax.set_ylim(bottom=0)
    maximum = max(stock["people_awaiting_initial_decision"].max(),
                  wip["Total Work In Progress"].max(), returns["rolling_12m_returns"].max())
    format_count_axis(ax.yaxis, maximum)
    ax.set_ylabel("People, cases or returns", color=MUTED)
    ax.set_title("Waiting stocks and returns over time", loc="left", color=INK, fontsize=15, pad=14)
    style_quarter_axis(ax, "2010-01-01", "2026-06-30")
    add_legend(fig, ax, ncol=3, fontsize=8.5)
    save_chart(fig, "stock-vs-returns")


def write_outputs(metadata, tables, quarterly, work_in_progress, support):
    DERIVED.mkdir(parents=True, exist_ok=True)
    headlines = make_headlines(metadata, tables, quarterly, work_in_progress, support)
    (DERIVED / "tables.json").write_text(
        json.dumps({"source": metadata, "tables": tables}, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (DERIVED / "headline.json").write_text(
        json.dumps(headlines, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    pd.DataFrame(annual_rows(tables)).to_csv(DERIVED / "annual-summary.csv", index=False)

    records = []
    for sheet, table in tables.items():
        for row in table["rows"]:
            for column, value in row["values"].items():
                records.append({"sheet": sheet, "row": row["label"], "column": column, "value": value})
    pd.DataFrame(records).to_csv(DERIVED / "all-table-values.csv", index=False)

    latest = headlines["year_ending_june_2026"]
    pd.DataFrame([{"measure": key, "value": value} for key, value in latest.items()]).to_csv(
        DERIVED / "year-ending-june-2026.csv", index=False
    )
    quarterly_flows_with_rolling_returns(quarterly).to_csv(
        DERIVED / "quarterly-flows.csv", index=False, lineterminator="\n", na_rep=""
    )
    support_series(support).to_csv(
        DERIVED / "quarterly-support-accommodation.csv", index=False, lineterminator="\n", na_rep=""
    )
    hotel_region_breakdown(support).to_csv(
        DERIVED / "hotel-by-region.csv", index=False, lineterminator="\n", na_rep=""
    )
    work_in_progress_stages(work_in_progress).to_csv(
        DERIVED / "work-in-progress-stages.csv", index=False, lineterminator="\n", na_rep=""
    )
    inadmissibility_series(tables).to_csv(
        DERIVED / "inadmissibility.csv", index=False, lineterminator="\n", na_rep=""
    )
    chart_claims_by_nationality(tables)
    chart_claims_by_age(tables)
    chart_claims_by_route(tables)
    chart_nationality_routes(tables)
    chart_grant_types(tables)
    chart_children_decisions(tables)
    chart_uasc_grant_rate(tables)
    chart_age_assessments(tables)
    chart_annual_flows(tables)
    chart_grant_rates(tables)
    chart_small_boat_rates(tables)
    chart_inadmissibility_quarterly(tables)
    chart_inadmissibility_totals(tables)
    chart_waiting_times(tables)
    chart_support(tables)
    chart_hotel_accommodation(support)
    chart_hotel_regions(support)
    chart_quarterly_flows(quarterly)
    chart_quarterly_decision_outcomes(quarterly)
    chart_work_in_progress_stages(work_in_progress)
    chart_stock_and_returns(quarterly, work_in_progress)


def main():
    metadata, tables = load_tables()
    validate_tables(tables)
    quarterly, work_in_progress = load_quarterly_data()
    validate_quarterly_data(tables, quarterly, work_in_progress)
    support = load_support_data()
    validate_support_data(tables, support)
    write_outputs(metadata, tables, quarterly, work_in_progress, support)
    print("Parsed 18 summary tables and pinned quarterly data; source fingerprints and reconciliations validated.")


if __name__ == "__main__":
    main()