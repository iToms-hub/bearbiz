import pytest

from apps.reports.missed_opportunities import parse_missed_opportunity_text


def report(location, sales, missed_customers, missed_sales, target_sales):
    return f"""Week: 41. Week Ending Date: 11/14/2026
Missed Opportunities Report
{location}
Sun ${sales} 100 4.0 10 10.0 % $10 1.0 {missed_customers} ${missed_sales}
Mon $2,000 100 4.0 10 10.0 % $10 1.0
Tue $3,000 100 4.0 10 10.0 % $10 1.0
Wed $4,000 100 4.0 10 10.0 % $10 1.0
Thu $5,000 100 4.0 10 10.0 % $10 1.0
Fri $6,000 100 4.0 10 10.0 % $10 1.0
Sat $7,000 100 4.0 10 10.0 % $10 1.0
Total ${sales} 700 4.0 10.0 % $10 1.0 {missed_customers} ${missed_sales}
Target ${target_sales} 700 4.0 10.0 % $10 1.0
"""


def test_multi_location_selects_temecula_only():
    temecula = report("1214 The Promenade in Temecula", "21,774", "39", "1,787", "29,400")
    other = report("1560 North County Mall", "99,999", "88", "9,999", "88,888")
    parsed = parse_missed_opportunity_text(temecula + other)
    assert parsed["total"]["store_sales"] == "$21,774"
    assert parsed["total"]["missed_customers"] == "39"
    assert parsed["total"]["missed_store_sales"] == "$1,787"
    assert parsed["target"]["store_sales"] == "$29,400"
    assert len(parsed["days"]) == 7
    assert parsed["days"][0]["store_sales"] == "$21,774"


def test_report_title_without_location_heading_remains_compatible():
    text = report("1214 The Promenade in Temecula", "21,774", "39", "1,787", "29,400")
    text = text.replace("1214 The Promenade in Temecula\n", "")
    assert parse_missed_opportunity_text(text)["total"]["store_sales"] == "$21,774"


def test_headerless_single_section_remains_compatible():
    text = report("1214 The Promenade in Temecula", "21,774", "39", "1,787", "29,400")
    text = text.replace("Missed Opportunities Report\n1214 The Promenade in Temecula\n", "")
    assert parse_missed_opportunity_text(text)["total"]["store_sales"] == "$21,774"


def test_missing_target_fails_closed_in_multilocation_report():
    text = report("1214 Other Location", "21,774", "39", "1,787", "29,400") + report("1560 North County Mall", "99,999", "88", "9,999", "88,888")
    with pytest.raises(ValueError, match="Temecula"):
        parse_missed_opportunity_text(text)


def test_ambiguous_target_location_fails_clearly():
    text = report("1214 The Promenade in Temecula", "21,774", "39", "1,787", "29,400") + report("999 The Promenade in Temecula", "99,999", "88", "9,999", "88,888")
    with pytest.raises(ValueError, match="ambiguous"):
        parse_missed_opportunity_text(text)


def test_non_temecula_single_section_fails_closed():
    text = report("1560 North County Mall", "99,999", "88", "9,999", "88,888")
    with pytest.raises(ValueError, match="Temecula"):
        parse_missed_opportunity_text(text)


def test_multiple_locations_without_report_markers_fail_closed():
    text = report("1214 Other Location", "21,774", "39", "1,787", "29,400") + report("1560 North County Mall", "99,999", "88", "9,999", "88,888")
    text = text.replace("Missed Opportunities Report\n", "")
    with pytest.raises(ValueError, match="Temecula"):
        parse_missed_opportunity_text(text)
