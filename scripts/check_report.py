"""Check that published report claims and local download links match the data."""
import re
from pathlib import Path

from analyze import (
    ROOT,
    load_quarterly_data,
    load_support_data,
    load_tables,
    make_headlines,
    validate_quarterly_data,
    validate_support_data,
    validate_tables,
    work_in_progress_stages,
)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    report_path = ROOT / "index.qmd"
    report = report_path.read_text(encoding="utf-8")
    metadata, tables = load_tables()
    validate_tables(tables)
    quarterly, work_in_progress = load_quarterly_data()
    validate_quarterly_data(tables, quarterly, work_in_progress)
    support = load_support_data()
    validate_support_data(tables, support)
    headlines = make_headlines(metadata, tables, quarterly, work_in_progress, support)
    annual = headlines["calendar_2025"]
    latest = headlines["year_ending_june_2026"]
    returns_and_stock = headlines["returns_and_stock"]
    small_boat = headlines["small_boat_case_grant_rates"]
    hotel = headlines["hotel_accommodation"]
    who_claims = headlines["who_claims"]
    decisions = headlines["decisions"]
    children = headlines["children"]
    wip = headlines["work_in_progress"]
    awaiting_comparison = headlines["awaiting_comparison"]

    require(annual["people_claiming_asylum"] == 101911, "Calendar 2025 claims changed from the report headline.")
    require(round(annual["published_initial_grant_rate_main_applicants"] * 100, 1) == 42.1,
            "The calendar 2025 main-applicant grant rate changed.")
    require(latest["people_awaiting_initial_decision"] == 40168, "June 2026 pending people changed.")
    require(latest["people_receiving_initial_decisions"] == 115872, "June 2026 initial decisions changed.")
    require(latest["withdrawals"] == 16265, "June 2026 withdrawals changed.")
    require(latest["grants_of_protection_or_other_leave"] + latest["refusals"] == 115872,
            "June 2026 grants and refusals no longer reconcile to initial decisions.")
    require(round(latest["published_initial_grant_rate_main_applicants"] * 100, 1) == 38.1,
            "The June 2026 main-applicant grant rate changed.")
    require(round(small_boat["year_ending_june_2025"] * 100, 1) == 55.7
            and round(small_boat["year_ending_june_2026"] * 100, 1) == 47.7,
            "The published case-based small-boat rates changed.")
    require(returns_and_stock["latest_quarter"] == "2026 Q2"
            and returns_and_stock["quarterly_claims"] == 17233
            and returns_and_stock["quarterly_substantive_decisions"] == 19079
            and returns_and_stock["quarterly_asylum_related_returns"] == 3157
            and returns_and_stock["rolling_12_month_asylum_related_returns"] == 12568
            and returns_and_stock["people_awaiting_initial_decision"] == 40168
            and returns_and_stock["total_work_in_progress_cases"] == 224742,
            "The quarterly returns or stock figures changed.")
    require(hotel["peak_quarter"] == "2023 Q3" and hotel["peak_people"] == 56018
            and hotel["latest_quarter"] == "2026 Q2" and hotel["latest_people"] == 16021
            and hotel["latest_total_supported"] == 93293
            and hotel["largest_region_latest"] == "London"
            and hotel["largest_region_latest_people"] == 5487,
            "The quarterly hotel or regional accommodation figures changed.")
    require(who_claims["top_nationality"] == "Pakistan"
            and who_claims["top_nationality_people"] == 8305
            and who_claims["uasc_people"] == 4275
            and who_claims["small_boat_people"] == 33949
            and round(who_claims["small_boat_share"] * 100, 1) == 39.5
            and who_claims["visas_and_other_leave_people"] == 34999
            and round(who_claims["visas_and_other_leave_share"] * 100, 1) == 40.7,
            "The Who claims asylum headline figures changed.")
    require(decisions["claims"] == 85891
            and decisions["substantive_decisions"] == 115872
            and decisions["grants"] == 42394
            and decisions["refusals"] == 73478
            and decisions["withdrawals"] == 16265
            and decisions["asylum_related_grants"] == 42394
            and decisions["resettlement_arrivals"] == 3840
            and decisions["total_grants_and_arrivals"] == 46234,
            "The year-ending-June 2026 claims and decision figures changed.")
    require(children["children_decisions"] == 17529
            and children["children_granted"] == 6518
            and children["children_refused"] == 11011
            and children["uasc_decisions"] == 4051
            and children["uasc_granted"] == 2329
            and children["uasc_refused"] == 1722
            and round(children["uasc_grant_rate"] * 100, 1) == 57.5
            and children["age_assessments_raised"] == 6409
            and children["age_assessments_closed"] == 6265
            and children["age_assessments_17_and_under"] == 3512
            and children["age_assessments_18_and_over"] == 2753,
            "The year-ending-June 2026 child decision or age-assessment figures changed.")
    stages = work_in_progress_stages(work_in_progress).set_index("Quarter")
    require(wip["latest_quarter"] == "2024 Q2"
            and wip["total_cases"] == 224742
            and wip["awaiting_initial_decision_cases"] == 87217
            and wip["not_awaiting_initial_decision_cases"] == 137525
            and round(wip["awaiting_initial_decision_share"] * 100, 1) == 38.8
            and round(wip["not_awaiting_initial_decision_share"] * 100, 1) == 61.2
            and stages.loc["2023 Q2", "decided_excluding_on_hold"] == 63097,
            "The published WIP count, stage split or earlier decision-status bound changed.")
    require(awaiting_comparison["june_2024"]["people"] == 118882
            and awaiting_comparison["june_2024"]["main_applicant_cases"] == 85839
            and awaiting_comparison["june_2024"]["dependants"] == 33043
            and awaiting_comparison["june_2024"]["wip_awaiting_cases"] == 87217
            and awaiting_comparison["june_2024"]["publication_difference_cases"] == 1378
            and awaiting_comparison["june_2026"]["people"] == 40168
            and awaiting_comparison["june_2026"]["main_applicant_cases"] == 32401
            and awaiting_comparison["june_2026"]["dependants"] == 7767,
            "The same-date D03 and ASY_03 pending counts or June 2026 unit split changed.")

    claims = [
        "101,911", "42.1%", "38.1%", "40,168", "32,401", "85,891", "115,872",
        "42,394", "73,478", "33,949", "42,389", "55.7%", "47.7%", "93,293",
        "16,021", "12,568", "3,841", "8,727", "9,009", "Official Statistics in Development",
        "16,265 withdrawals", "grants plus refusals", "administrative outcomes",
        "otherwise closed", "COUNT_AXIS_K_THRESHOLD", "Chart legends sit below the plot area",
        "8,305 people", "4,275 UASC claims", "33,949 claims by small boat",
        "34,999 following visas or other leave", "6,125 were recorded under small boat",
        "7,324 of 8,305 claims", "by up to seven people", "avoiding double-counting",
        "UASC` means **Unaccompanied Asylum-Seeking Child**", "separated from both parents",
        "42,394 asylum-related grants", "3,840 resettlement arrivals",
        "shown as zero only to render the chart",
        "In 2024, the published total is one higher than the sum of the grant components and resettlement arrivals",
        "A claim and an outcome in the same quarter do not necessarily concern the same people",
        "17,529 initial decisions involving children", "6,518 resulted in grants",
        "11,011 in refusals", "4,051 UASC", "2,329 were granted and 1,722 refused",
        "57.5%", "6,409 assessments were raised", "6,265 were closed",
        "3,512 recorded an assessment of 17 and under", "2,753 recorded 18 and over",
        "the age category is the assessment’s finding",
        "17,233", "19,079", "3,157", "12,568", "224,742", "Monthly counts are not published",
        "latest seven quarters are provisional", "refused entry at port", "main-applicant cases",
        "56,018 people in September 2023", "Section 98 line is a separate historical category",
        "not a hotel count", "regardless of support eligibility", "London had the largest regional count",
        "5,487 people", "before 31 March 2023", "not counts of households or hotel rooms",
        "not be subtracted from either stock", "not a complete estimate of every asylum seeker currently in the UK",
        "224,742 main-applicant cases", "87,217 (38.8%)", "137,525 (61.2%)",
        "On Hold” includes people who may be either before or after a decision",
        "The 2024 “Post Decision” segment has no further breakdown",
        "not a current 2026 total", "different dates and use different units",
        "118,882 people", "85,839 main applicants and 33,043 dependants",
        "32,401 main applicants and 7,767 dependants", "87,217 in ASY_03",
        "85,839 in D03 and 87,217 in ASY_03, a difference of 1,378 cases",
        "separately compiled publications", "the two publications are not interchangeable",
        "2010 Q1 to 2026 Q2",
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
        "data/derived/quarterly-flows.csv",
        "data/raw/asylum-work-in-progress.csv",
        "data/derived/work-in-progress-stages.csv",
        "data/raw/support-accommodation-extract.csv",
        "data/derived/quarterly-support-accommodation.csv",
        "data/derived/hotel-by-region.csv",
        "data/raw/quarterly-sources.json",
    ]:
        require((ROOT / path).is_file(), f"Report download target does not exist: {path}")

    download = report.split("## Download the data", 1)
    require(len(download) == 2, "Download section is missing.")
    content = download[1].split("\n## Related reports", 1)[0]
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", content)
    require(len(links) == 13, "Expected thirteen reader-facing data download links.")
    for link in links:
        require((ROOT / link).is_file(), f"Download target does not exist: {link}")

    for chart in [
        "claims-by-nationality.svg", "claims-by-age.svg", "claims-by-route.svg", "nationality-routes.svg",
        "grant-types.svg", "children-decisions.svg", "uasc-grant-rate.svg", "age-assessments.svg",
        "annual-claims-decisions.svg", "initial-grant-rates.svg", "small-boat-grant-rates.svg",
        "waiting-times.svg", "asylum-support.svg", "quarterly-flows-returns.svg",
        "quarterly-claims-outcomes.svg", "stock-vs-returns.svg",
        "hotel-accommodation.svg", "hotel-by-region.svg", "work-in-progress-stages.svg",
    ]:
        require((ROOT / "assets" / chart).is_file(), f"Expected report chart is missing: {chart}")
        require(f"assets/{chart}" in report, f"Report does not reference its chart: {chart}")

    print("Report QA passed: pinned figures, unit distinctions, nineteen charts and thirteen downloads are consistent.")


if __name__ == "__main__":
    main()