import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyze import (  # noqa: E402
    SHEETS,
    cell_value,
    header_text,
    load_tables,
    parse_table,
    validate_tables,
    value_for,
)


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