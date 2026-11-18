import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze  # noqa: E402
from analyze import (
    SHEETS,
    cell_value,
    format_count,
    hotel_region_breakdown,
    header_text,
    load_quarterly_data,
    load_support_data,
    load_tables,
    parse_table,
    quarterly_flows_with_rolling_returns,
    support_series,
    validate_quarterly_data,
    validate_support_data,
    validate_tables,
    value_for,
)
from prepare_quarterly import count_value  # noqa: E402


def test_count_axis_labels_use_separators_or_k_when_the_scale_warrants_it():
    assert format_count(0, 0) == "0"
    assert format_count(950, 950) == "950"
    assert format_count(4500, 9000) == "4,500"
    assert format_count(9999, 9999) == "9,999"
    assert format_count(10_000, 10_000) == "10K"
    assert format_count(12_500, 125_000) == "12.5K"
    assert format_count(0, 20_000) == "0"
    assert format_count(20_000, 20_000) == "20K"
    assert format_count(125_000, 125_000) == "125K"


def test_all_chart_legends_are_outside_the_plot_area(monkeypatch):
    _, tables = load_tables()
    quarterly, work_in_progress = load_quarterly_data()
    support = load_support_data()
    rendered = []
    monkeypatch.setattr(analyze, "save_chart", lambda fig, name: rendered.append((name, fig)))

    try:
        analyze.chart_annual_flows(tables)
        analyze.chart_small_boat_rates(tables)
        analyze.chart_waiting_times(tables)
        analyze.chart_hotel_accommodation(support)
        analyze.chart_hotel_regions(support)
        analyze.chart_quarterly_flows(quarterly)
        analyze.chart_stock_and_returns(quarterly, work_in_progress)

        assert {name for name, _ in rendered} == {
            "annual-claims-decisions", "small-boat-grant-rates", "waiting-times",
            "hotel-accommodation", "hotel-by-region", "quarterly-flows-returns", "stock-vs-returns",
        }
        for name, fig in rendered:
            fig.canvas.draw()
            assert len(fig.legends) == 1, name
            assert fig.axes[0].get_legend() is None, name
            legend = fig.legends[0]
            renderer = fig.canvas.get_renderer()
            assert not legend.get_window_extent(renderer).overlaps(
                fig.axes[0].get_window_extent(renderer)
            ), name
            decorations_bottom = fig.axes[0].get_tightbbox(renderer).y0
            legend_top = max(
                artist.get_window_extent(renderer).y1
                for artist in [*legend.get_texts(), *legend.legend_handles]
            )
            gap_points = (decorations_bottom - legend_top) * 72 / fig.dpi
            assert gap_points >= 14, f"{name}: legend is {gap_points:.1f}pt below the axis label"
    finally:
        for _, fig in rendered:
            analyze.plt.close(fig)


def test_suppressed_quarterly_source_markers_remain_missing():
    assert count_value(":") is None
    assert count_value("-") is None
    assert count_value(0) == 0


def test_suppressed_values_stay_missing_and_year_headers_are_normalised():
    assert cell_value("z") is None
    assert cell_value(":") is None
    assert cell_value(0) == 0
    assert header_text(2025.0) == "2025"
    assert header_text("2022.0") == "2022"


def test_tables_parse_with_expected_headers_and_calendar_coverage():
    metadata, tables = load_tables()
    assert len(tables) == len(SHEETS) == 18
    assert tables["Asy_00a"]["columns"][0] == "2010"
    assert "Year ending June 2026" in tables["Asy_00a"]["columns"]
    assert tables["Asy_02d"]["columns"][-1] == "Grant rate - year ending June 2026 (cases)"
    assert metadata["sha256"]
    validate_tables(tables)


def test_core_totals_and_main_applicant_rate_match_the_saved_release():
    _, tables = load_tables()
    assert value_for(tables["Asy_00a"], "People claiming asylum", "Year ending June 2026") == 85891
    assert value_for(tables["Asy_00a"], "People awaiting an initial decision", "Year ending June 2026") == 40168
    assert round(value_for(tables["Asy_00a"], "Grant rate at initial decision", "Year ending June 2026"), 3) == 0.381
    assert value_for(tables["Asy_01c"], "Small Boat", "Year ending June 2026") == 33949
    assert value_for(tables["Asy_01d"], "Total", "Small Boat") == 33949


def test_quarterly_flows_and_stock_reconcile_to_summary_and_preserve_units():
    _, tables = load_tables()
    quarterly, work_in_progress = load_quarterly_data()
    validate_quarterly_data(tables, quarterly, work_in_progress)
    flows = quarterly_flows_with_rolling_returns(quarterly)
    latest = flows.iloc[-1]
    assert len(quarterly) == 66
    assert latest["quarter"] == "2026 Q2"
    assert latest["claims"] == 17233
    assert latest["substantive_decisions"] == 19079
    assert latest["asylum_related_returns"] == 3157
    assert latest["rolling_12m_returns"] == 12568
    assert latest["people_awaiting_initial_decision"] == 40168
    assert work_in_progress.loc[
        work_in_progress["Quarter"] == "2024 Q2", "Total Work In Progress"
    ].iloc[0] == 224742


def test_quarterly_hotel_series_section_98_and_regional_breakdown_reconcile():
    _, tables = load_tables()
    support = load_support_data()
    validate_support_data(tables, support)
    series = support_series(support)
    assert len(series) == 50
    assert series.iloc[0]["quarter"] == "2014 Q1"
    assert series.iloc[-1]["quarter"] == "2026 Q2"

    section_98 = series.loc[series["quarter"] == "2022 Q3"].iloc[0]
    assert section_98["section_98"] == 37142
    assert pd.isna(section_98["hotel"])
    dec_2022 = series.loc[series["quarter"] == "2022 Q4"].iloc[0]
    assert dec_2022["hotel"] == 45753
    assert pd.isna(dec_2022["section_98"])

    hotels = series.dropna(subset=["hotel"])
    peak = hotels.loc[hotels["hotel"].idxmax()]
    latest = hotels.iloc[-1]
    assert len(hotels) == 15
    assert peak["quarter"] == "2023 Q3"
    assert peak["hotel"] == 56018
    assert latest["hotel"] == 16021
    assert latest["total_supported"] == 93293

    regions = hotel_region_breakdown(support)
    for quarter in ("2023 Q3", "2026 Q2"):
        regional = regions.loc[regions["quarter"] == quarter]
        national = series.loc[series["quarter"] == quarter, "hotel"].iloc[0]
        assert regional["people"].sum() == national
    london = regions.loc[(regions["quarter"] == "2026 Q2") & (regions["uk_region"] == "London")]
    assert london["people"].iloc[0] == 5487


def test_small_boat_case_rate_is_not_a_people_rate():
    _, tables = load_tables()
    table = tables["Asy_02d"]
    rate = value_for(table, "All nationalities", "Grant rate - year ending June 2026 (cases)")
    decisions = value_for(table, "All nationalities", "Initial decisions - year ending June 2026 (cases)")
    assert round(rate, 3) == 0.477
    assert decisions == 42348


def test_header_discovery_uses_the_table_marker_and_keeps_categories():
    raw = pd.DataFrame([
        ["Example table", None, None],
        ["Notes", None, None],
        ["Year of claim", "2024.0", "2025"],
        ["Total", 3, 5],
    ])
    parsed = parse_table("Asy_04", raw)
    assert parsed["columns"] == ["2024", "2025"]
    assert parsed["rows"] == [{"label": "Total", "values": {"2024": 3, "2025": 5}}]