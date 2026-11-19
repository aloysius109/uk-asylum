"""Check that published report claims and local download links match the data."""
import re
from pathlib import Path

from analyze import (
    ROOT,
    load_quarterly_data,
    load_queue_indicators,
    load_support_data,
    load_tables,
    load_unhcr_fvp_stages,
    make_headlines,
    validate_quarterly_data,
    validate_queue_indicators,
    validate_support_data,
    validate_tables,
    validate_unhcr_fvp_stages,
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
    queue_indicators = load_queue_indicators()
    validate_queue_indicators(queue_indicators, work_in_progress)
    unhcr_fvp_stages = load_unhcr_fvp_stages()
    validate_unhcr_fvp_stages(unhcr_fvp_stages)
    headlines = make_headlines(
        metadata, tables, quarterly, work_in_progress, support, queue_indicators, unhcr_fvp_stages
    )
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
    inadmissibility = headlines["inadmissibility"]
    wip_now = headlines["wip_now"]
    fvp = headlines["face_value_productivity"]
    fvp_grant_rate = headlines["fvp_grant_rate"]
    unhcr_fvp = headlines["unhcr_fvp_reconciliation"]
    cohorts = headlines["cohorts"]
    inadmissibility_nationality = headlines["inadmissibility_nationality"]

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
    require(fvp["latest_period"] == "Year ending June 2026"
            and fvp["latest_claims"] == 85891
            and fvp["latest_all_initial_outcomes"] == 134484
            and round(fvp["latest_fvp_all_per_100"], 1) == 156.6
            and round(fvp["calendar_2022_fvp_all_per_100"], 1) == 32.7
            and round(fvp["calendar_2025_fvp_all_per_100"], 1) == 157.7
            and round(fvp["calendar_2025_fvp_substantive_per_100"], 1) == 133.2
            and fvp["calendar_2022_decisions_minus_claims"] == -63933
            and fvp["calendar_2025_decisions_minus_claims"] == 58819
            and fvp["cumulative_decisions_minus_claims_2010_2025"] == -46892,
            "The face-value productivity ratios or outcome-claims gaps changed.")
    fvp_correlations = fvp_grant_rate["correlations"]
    require(fvp_grant_rate["calendar_years"] == 16
            and round(fvp_grant_rate["fvp_2022"], 1) == 32.7
            and round(fvp_grant_rate["grant_rate_2022"] * 100, 1) == 75.9
            and fvp_correlations["same_year"] == {"pearson_r": -0.42, "n": 16}
            and fvp_correlations["next_year"] == {"pearson_r": -0.72, "n": 15}
            and fvp_correlations["next_year_excluding_2022_2023"] == {"pearson_r": -0.45, "n": 13}
            and fvp_correlations["waiting_stock_same_year"] == {"pearson_r": 0.87, "n": 16}
            and fvp_correlations["withdrawal_admin_share_same_year"] == {"pearson_r": 0.82, "n": 16},
            "The FVP and grant-rate association figures changed.")
    require(unhcr_fvp["unhcr_applications_all_stages"] == 168185
            and unhcr_fvp["unhcr_decisions_all_stages"] == 194877
            and round(unhcr_fvp["unhcr_fvp_all_stages_per_100"], 1) == 115.9
            and round(unhcr_fvp["stage_values"]["FI"]["fvp_per_100"], 1) == 158.1
            and round(unhcr_fvp["stage_values"]["AR"]["fvp_per_100"], 1) == 41.5
            and round(unhcr_fvp["stage_values"]["RA"]["fvp_per_100"], 1) == 201.5
            and round(unhcr_fvp["home_office_fvp_per_100"], 1) == 157.7
            and round(unhcr_fvp["first_instance_fvp_difference_from_home_office"], 1) == 0.4,
            "The UNHCR and Home Office FVP stage reconciliation changed.")
    require(cohorts["cohort_years"] == 16
            and round(cohorts["cohort_2010_initial_grant_rate"] * 100, 1) == 27.2
            and round(cohorts["cohort_2010_latest_grant_rate"] * 100, 1) == 50.0
            and round(cohorts["cohort_2022_initial_grant_rate"] * 100, 1) == 60.3
            and round(cohorts["cohort_2022_latest_grant_rate"] * 100, 1) == 68.0
            and cohorts["cohort_2025_claims"] == 82559
            and cohorts["cohort_2025_not_yet_known"] == 9009
            and round(cohorts["cohort_2025_initial_grant_rate"] * 100, 1) == 44.5
            and round(cohorts["cohort_2025_latest_grant_rate"] * 100, 1) == 46.7
            and round(cohorts["cohort_2025_returns_per_100_latest_refusals"], 1) == 9.7,
            "The claim-cohort outcome figures changed.")
    require(inadmissibility_nationality["notices_total"] == 51228
            and inadmissibility_nationality["top_nationality"] == "Afghanistan"
            and inadmissibility_nationality["top_nationality_notices"] == 12416
            and inadmissibility_nationality["source_other"] == 148,
            "The inadmissibility notice nationality figures changed.")
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
    require(wip_now["latest_full_wip_quarter"] == "2024 Q2"
            and wip_now["latest_full_wip_cases"] == 224742
            and wip_now["latest_full_wip_post_decision_cases"] == 137525
            and wip_now["initial_decision_cases_june_2024"] == 87217
            and wip_now["initial_decision_cases_june_2026"] == 33514
            and wip_now["initial_decision_cases_reduction"] == 53703
            and round(wip_now["initial_decision_cases_reduction_share"] * 100, 1) == 61.6
            and wip_now["latest_pending_people"] == 40168
            and wip_now["latest_pending_main_applicant_cases"] == 32401
            and wip_now["tribunal_asylum_protection_cases_june_2024"] == 33227
            and wip_now["tribunal_asylum_protection_cases_june_2026"] == 90341
            and wip_now["tribunal_asylum_protection_cases_increase"] == 57114
            and wip_now["tribunal_total_open_cases_june_2026"] == 155798,
            "The current WIP indicators or the comparison to June 2024 changed.")
    require(inadmissibility["period"] == "2021 Q1 to 2026 Q2"
            and inadmissibility["identified"] == 108455
            and inadmissibility["notices_of_intent"] == 51228
            and inadmissibility["decisions_served"] == 1268
            and inadmissibility["removals"] == 1133
            and inadmissibility["subsequently_admitted"] == 105828
            and round(inadmissibility["admitted_to_identified_event_ratio"] * 100, 1) == 97.6
            and round(inadmissibility["removals_to_identified_event_ratio"] * 100, 1) == 1.0
            and inadmissibility["latest_quarter"] == "2026 Q2"
            and inadmissibility["latest_identified"] == 1979
            and inadmissibility["latest_admitted"] == 981
            and inadmissibility["latest_removals"] == 650,
            "The published inadmissibility event totals, period or ratios changed.")

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
        "face-value productivity (FVP)", "outcomes per 100 claims", "32.7 outcomes per 100 claims in 2022",
        "139.9 in 2023", "157.7 in 2025", "134,484 outcomes against 85,891 claims",
        "156.6 per 100", "63,933 below claims", "58,819 above claims", "−46,892",
        "not an estimate of the current backlog", "may include legacy claims from before this series begins",
        "staff productivity or waiting-time measures", "only from 2020",
        "Why does Asylum Tracker show 116 for UK 2025?", "Both measures express recorded decisions per 100 applications",
        "Appeal/review (AR) | 62,732 | 26,016 | Cases", "| All three procedures | 168,185 | 194,877 | Mixed | 115.9 |",
        "first instance alone: **158.1 per 100 applications**", "only 0.4 points above the Home Office’s calendar-2025 **157.7**",
        "adds persons and cases without conversion", "not like-for-like totals",
        "report’s **156.6** figure is for the separate rolling year ending June 2026",
        "Pearson correlation between FVP and the Home Office’s published initial grant rate is **−0.42**",
        "**−0.72**, 15 year-pairs", "excluding grant-rate years 2022–23",
        "year-end vs grant rate in the same year", "Withdrawals and administrative outcomes count in FVP",
        "do not establish cause and effect", "An_inspection_of_asylum_casework_June_to_October_2023.pdf",
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
        "Subsequent-admission events", "Identification events", "Enforced removal events",
        "97.6% of identification events in the period", "1.0% of identification events",
        "not a linked-person rate", "not outcomes linked to the same people",
        "should not be read as a conversion funnel", "latest seven quarters are provisional",
        "enforced removals, not voluntary returns", "rise sharply from 2025 Q4",
        "returns to France under the UK–France agreement",
        "What does “inadmissibility” mean, and when did it begin?", "safe third country",
        "1 January 2021", "paragraphs 345A–345D", "sections 80B–80C",
        "28 June 2022", "Why are so many later admitted to the UK asylum process?",
        "paragraph 345D", "must be admitted for consideration in the UK",
        "38 removal events from January 2021 through June 2025", "6 August 2025",
        "1,087 returns to France", "limited practical transfer routes",
        "only the wait for an initial decision", "total time people spend in the asylum system is likely to be longer",
        "137,525 main-applicant cases", "These WIP figures are cases, whereas `Asy_03a` durations count people",
        "does not publish durations for post-decision cases",
        "The current total WIP is not published", "137,525 “Post Decision” cases",
        "should not all be described as waiting for appeals or reviews", "does not break them down further",
        "Note 25 cautions that this aggregate is inflated by cases for which a decision had already been served",
        "87,217 applications in June 2024", "33,514 in June 2026", "61.6% decrease",
        "90,341 open cases in its Asylum/Protection and Revocation of Protection caseload",
        "33,227 in June 2024", "cannot be added to estimate WIP",
        "published data do not establish which", "32,401 main-applicant cases",
        "FIA_4", "different coverage and are not additive", "2016 Q4 to 2026 Q2",
        "2010 Q1 to 2026 Q2", "provides a nationality breakdown for **notices of intent only** in `Asy_02f`",
        "**51,228 notice events**", "Afghanistan (**12,416**)", "not a count of distinct people",
        "27.2% at initial decision to 50.0% on the latest known substantive outcomes", "60.3% to 68.0%",
        "9,009 of its 82,559 claims", "latest outcome recorded",
        "returns recorded against each claim-year cohort", "not a person-level return rate",
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
        "data/derived/face-value-productivity.csv",
        "data/derived/fvp-grant-rate.csv",
        "data/derived/cohort-outcomes.csv",
        "data/derived/inadmissibility-nationality.csv",
        "data/raw/unhcr-gbr-fvp-stages.csv",
        "data/raw/asylum-work-in-progress.csv",
        "data/derived/work-in-progress-stages.csv",
        "data/derived/queue-indicators.csv",
        "data/derived/inadmissibility.csv",
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
    require(len(links) == 20, "Expected twenty reader-facing data download links.")
    for link in links:
        require((ROOT / link).is_file(), f"Download target does not exist: {link}")

    for chart in [
        "claims-by-nationality.svg", "claims-by-age.svg", "claims-by-route.svg", "nationality-routes.svg",
        "grant-types.svg", "children-decisions.svg", "uasc-grant-rate.svg", "age-assessments.svg",
        "annual-claims-decisions.svg", "initial-grant-rates.svg", "small-boat-grant-rates.svg",
        "waiting-times.svg", "asylum-support.svg", "quarterly-flows-returns.svg",
        "quarterly-claims-outcomes.svg", "face-value-productivity.svg", "decisions-minus-claims.svg",
        "fvp-grant-rate.svg",
        "inadmissibility-nationality.svg", "cohort-latest-outcomes.svg", "cohort-grant-rates.svg",
        "cohort-returns.svg",
        "stock-vs-returns.svg",
        "hotel-accommodation.svg", "hotel-by-region.svg", "work-in-progress-stages.svg",
        "inadmissibility-quarterly.svg", "inadmissibility-totals.svg", "queue-shift.svg",
    ]:
        require((ROOT / "assets" / chart).is_file(), f"Expected report chart is missing: {chart}")
        require(f"assets/{chart}" in report, f"Report does not reference its chart: {chart}")

    print("Report QA passed: pinned figures, unit distinctions, twenty-nine charts and twenty downloads are consistent.")


if __name__ == "__main__":
    main()