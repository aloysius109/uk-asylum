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
ASSETS = ROOT / "assets"
DERIVED = ROOT / "data" / "derived"

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


def optional_value(table, label, column):
    row = row_for(table, label)
    return row["values"].get(column) if row else None


def numeric(value, context):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"Expected a numeric value for {context}; found {value!r}.")
    return float(value)


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


def make_headlines(metadata, tables):
    small_boat = tables["Asy_02d"]
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
    ax.legend(frameon=False, loc="upper left", fontsize=9)
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
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    save_chart(fig, "small-boat-grant-rates")


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
    ax.set_title(f"Waiting time at {latest_column}", loc="left", color=INK, fontsize=15, pad=14)
    ax.xaxis.grid(True, color=GRID, linewidth=.8)
    ax.yaxis.grid(False)
    ax.spines[["top", "right", "left", "bottom"]].set_visible(False)
    ax.tick_params(axis="x", colors=MUTED, labelsize=9, length=0, pad=7)
    ax.legend(frameon=False, loc="lower center", bbox_to_anchor=(.5, -0.5), ncol=2, fontsize=8)
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


def write_outputs(metadata, tables):
    DERIVED.mkdir(parents=True, exist_ok=True)
    headlines = make_headlines(metadata, tables)
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
    chart_annual_flows(tables)
    chart_grant_rates(tables)
    chart_small_boat_rates(tables)
    chart_waiting_times(tables)
    chart_support(tables)


def main():
    metadata, tables = load_tables()
    validate_tables(tables)
    write_outputs(metadata, tables)
    print("Parsed 18 Home Office tables; source fingerprint, calendar coverage and key totals validated.")


if __name__ == "__main__":
    main()