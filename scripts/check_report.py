"""Check that published report claims and local download links match the data."""
import re
from pathlib import Path

from analyze import ROOT, load_tables, make_headlines, validate_tables


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    report_path = ROOT / "index.qmd"
    report = report_path.read_text(encoding="utf-8")
    metadata, tables = load_tables()
    validate_tables(tables)
    headlines = make_headlines(metadata, tables)
    annual = headlines["calendar_2025"]
    latest = headlines["year_ending_june_2026"]
    small_boat = headlines["small_boat_case_grant_rates"]

    require(annual["people_claiming_asylum"] == 101911, "Calendar 2025 claims changed from the report headline.")
    require(round(annual["published_initial_grant_rate_main_applicants"] * 100, 1) == 42.1,
            "The calendar 2025 main-applicant grant rate changed.")
    require(latest["people_awaiting_initial_decision"] == 40168, "June 2026 pending people changed.")
    require(latest["people_receiving_initial_decisions"] == 115872, "June 2026 initial decisions changed.")
    require(latest["grants_of_protection_or_other_leave"] + latest["refusals"] == 115872,
            "June 2026 grants and refusals no longer reconcile to initial decisions.")
    require(round(latest["published_initial_grant_rate_main_applicants"] * 100, 1) == 38.1,
            "The June 2026 main-applicant grant rate changed.")
    require(round(small_boat["year_ending_june_2025"] * 100, 1) == 55.7
            and round(small_boat["year_ending_june_2026"] * 100, 1) == 47.7,
            "The published case-based small-boat rates changed.")

    claims = [
        "101,911", "42.1%", "38.1%", "40,168", "32,401", "85,891", "115,872",
        "42,394", "73,478", "33,949", "42,389", "55.7%", "47.7%", "93,293",
        "16,021", "12,568", "3,841", "8,727", "9,009", "Official Statistics in Development",
        "z", "2011 claim total in `Asy_00a` differs by six from `Asy_01a`",
    ]
    for claim in claims:
        require(claim in report, f"Expected pinned report claim is missing or changed: {claim}")

    for path in [
        "data/derived/annual-summary.csv",
        "data/derived/year-ending-june-2026.csv",
        "data/derived/all-table-values.csv",
        "data/derived/tables.json",
        "data/raw/asylum-summary-jun-2026.ods",
        "data/raw/source.json",
    ]:
        require((ROOT / path).is_file(), f"Report download target does not exist: {path}")

    download = report.split("## Download the data", 1)
    require(len(download) == 2, "Download section is missing.")
    content = download[1].split("\n## Related reports", 1)[0]
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", content)
    require(len(links) == 6, "Expected six reader-facing data download links.")
    for link in links:
        require((ROOT / link).is_file(), f"Download target does not exist: {link}")

    for chart in [
        "annual-claims-decisions.svg", "initial-grant-rates.svg", "small-boat-grant-rates.svg",
        "waiting-times.svg", "asylum-support.svg",
    ]:
        require((ROOT / "assets" / chart).is_file(), f"Expected report chart is missing: {chart}")
        require(f"assets/{chart}" in report, f"Report does not reference its chart: {chart}")

    print("Report QA passed: pinned figures, unit distinctions, five charts and six downloads are consistent.")


if __name__ == "__main__":
    main()