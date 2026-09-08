from __future__ import annotations

import pytest

from apps.reports.base import ParsedReport
from apps.reports.modules import load_builtin_reports
from apps.reports.modules.bonus_club import BonusClubReport
from apps.reports.modules.gift_cards import GiftCardsReport
from apps.reports.modules.ranking import RankingReport
from apps.reports.modules.segments import SegmentsReport
from apps.reports.modules.weekly_sales import WeeklySalesReport
from apps.reports.registry import all_reports, clear, get, history, register


class DummyReport:
    slug = "weekly_sales"
    display_name = "Weekly Sales"

    def parse(self, raw_text: str) -> ParsedReport:
        return ParsedReport(
            report_type=self.slug,
            source_name="weekly_sales.pdf",
            payload={"raw_text": raw_text},
        )


def test_parsed_report_defaults_payload_to_empty_dict() -> None:
    report = ParsedReport(report_type="weekly_sales", source_name="sample.pdf")
    assert report.payload == {}


def test_parsed_report_defaults_raw_rows_to_empty_list() -> None:
    report = ParsedReport(report_type="weekly_sales", source_name="sample.pdf")
    assert report.raw_rows == []


@pytest.mark.django_db
def test_weekly_sales_parser_uses_top_table_only() -> None:
    report = WeeklySalesReport().parse(
        """Weekly Sales Summary
Net Sales    1200
Orders    48
Week Ending    2026-09-06

Lower summary table
Net Sales    9999
Orders    1
"""
    )

    assert report.report_type == "weekly_sales"
    assert report.period_end == "2026-09-06"
    assert report.payload["summary_kpis"] == {
        "net_sales": 1200,
        "orders": 48,
        "period_end": "2026-09-06",
    }
    assert [row["value"] for row in report.raw_rows] == ["1200", "48", "2026-09-06"]


@pytest.mark.django_db
def test_weekly_sales_parser_reads_date_range_from_title_line() -> None:
    report = WeeklySalesReport().parse(
        """Statistics 2/1/2026 - 2/7/2026 1214 The Promenade in Temecula

Weekly Sales Summary
Net Sales    20366
Orders    410
"""
    )

    assert report.period_start == "2026-02-01"
    assert report.period_end == "2026-02-07"
    assert report.payload["fiscal"] is not None


def test_ranking_parser_extracts_target_store_rankings() -> None:
    report = RankingReport().parse(
        """FW: Week ending '26 FW01 (run for week ending 02/07/2026)

Store
Sales
Sales v
Plan
Sales v
LY
Trans
Trans v
LY
DPT
B/W v
LY
UPT
B/W v
LY
Parties
B/W v
LY
% 
Party 
Sales
# Reg 
GC
Amt Reg GC
Reg GC 
Amt 
B/W v 
LY
Skin 
Units
Traffic 
TY
Traffic 
B/W
Conv 
TY
Conv 
LY
Conv 
B/W
STAR
BC Cap
%
Stuffe
rs
Shoe
s
098 Mission Viejo
$8,333
-42.9 %
-40.5 %
201
-26.9 %
41.46
-9.48
3.47
-1.10
0
-1
0.0 %
5
$180
$170
179
987
-
37.57%
20.4 %
17.4 %
3.0 %
6.18
58.4 %
19.94
%
3.16%
214 Temecula
$20,248
-14.9 %
-12.7 %
426
-11.4 %
47.53
-0.70
3.84
-0.23
1
0
1.6 %
2
$100
N/A
404
2207
-
17.28%
19.3 %
18.0 %
1.3 %
10.47
67.0 %
15.76
%
5.31%
SOCAL/Vegas
$206,609
-21.6 %
-17.5 %
4,185
-18.7 %
49.37
0.71
4.07
-0.15
5
-5
0.7 %
44
$2,034
($534)
4056
20966
-
19.81%
20.0 %
19.7 %
0.3 %
8.72
77.8 %
17.34
%
4.99%
"""
    )

    assert report.report_type == "ranking"
    assert report.period_end == "2026-02-07"
    assert report.payload["fiscal"]["fiscal_week_number"] == 1
    assert report.payload["store_count"] == 2
    assert report.payload["target_store"]["store_number"] == "214"
    assert report.payload["target_store"]["ranks"]["sales"]["rank"] == 1
    assert report.payload["target_store"]["ranks"]["traffic_bw"]["rank"] == 2
    assert report.payload["target_store"]["ranks"]["conv_ty"]["rank"] == 2
    assert report.payload["viewer"]["headers"][0:2] == ["Week", "Date"]
    assert report.payload["viewer"]["values"][2] == "1/2"
    assert report.raw_rows[1]["store_name"] == "Temecula"


@pytest.mark.django_db
def test_segments_parser_extracts_manager_rows_and_store_total() -> None:
    report = SegmentsReport().parse(
        """Segment Accountability Report
1214 The Promenade in Temecula
8/23/2026 - 8/29/2026
Name / Job Title
# Seg
% Total
Success Segments
% Success
Store Sales
Sales Trans
Conversion
DPT
UPT
Visit Value
Vanessa Esparza
9
25.0 %
6
66.7 %
Act
$6,349
130
12.8
48.82
3.95
6.27
SL
Var
-$90
% Target
-1.4 %
Store Total
36
100.0 %
15
41.7 %
Act
$19,158
399
12.4
$48
3.72
$5.93
Var
-$1,941
% Target
-9.3 %
"""
    )

    assert report.report_type == "segments"
    assert report.period_end == "2026-08-29"
    assert report.payload["store_total"]["name"] == "Store Total"
    assert report.payload["manager_rows"][0]["name"] == "Vanessa Esparza"
    assert report.payload["manager_rows"][0]["visible_values"] == ["9", "25.0 %", "6", "66.7 %", "$6,349", "130", "12.8", "48.82", "3.95"]
    assert report.payload["viewer"]["headers"] == ["Name", "#seg", "% Total", "Success Segments", "% Success", "Store Sales", "Sales Trans", "Conversion", "DPT", "UPT"]
    assert report.payload["viewer"]["rows"][0]["values"][0] == "Vanessa Esparza"


@pytest.mark.django_db
def test_segments_parser_handles_flattened_live_rows() -> None:
    report = SegmentsReport().parse(
        """Segment Accountability Report
1214 The Promenade in Temecula
8/23/2026 - 8/29/2026
Name / Job Title # Seg % Total Success % Success Store Sales Sales Trans Conversion DPT UPT Visit Value
Segments Trans n
Vanessa Esparza 9 25.0 % 6 66.7 % Act $6,349 130 12.8 48.82 3.95 6.27
SL Var -$90
% Target -1.4 %
Store Total 36 100.0 % 15 41.7 % Act $19,158 399 12.4 $48 3.72 $5.93
Var -$1,941
% Target -9.3 %
Page 1 of 3 8/30/2026 4:03:19 AM
"""
    )

    assert report.payload["manager_rows"][0]["name"] == "Vanessa Esparza"
    assert report.payload["manager_rows"][0]["visible_values"] == ["9", "25.0 %", "6", "66.7 %", "$6,349", "130", "12.8", "48.82", "3.95"]
    assert report.payload["store_total"]["name"] == "Store Total"
    assert report.payload["store_total"]["visible_values"] == ["36", "100.0 %", "15", "41.7 %", "$19,158", "399", "12.4", "$48", "3.72"]
    report = RankingReport().parse(
        """Store by Store Comparison
214 Temecula $20,248 -14.9 % -12.7 % 426 -11.4 % 47.53 -0.70 3.84 -0.23 1 0 1.6 % 2 $100 N/A 404 2207 19.3 % 18.0 % 1.3 % 10.47 67.0 % 5.31%
098 Mission Viejo $8,333 -42.9 % -40.5 % 201 -26.9 % 41.46 -9.48 3.47 -1.10 0 -1 0.0 % 5 $180 $170 179 987 20.4 % 17.4 % 3.0 % 6.18 58.4 % 19.94 %
FW: Week ending '26 FW01 (run for week ending 02/07/2026)
"""
    )

    assert report.payload["target_store"]["store_number"] == "214"
    assert report.payload["target_store"]["ranks"]["sales"]["rank"] == 1
    assert report.payload["target_store"]["ranks"]["conv_ty"]["rank"] == 2
    assert report.payload["viewer"]["values"][2] == "1/2"


@pytest.mark.django_db
def test_gift_cards_parser_extracts_associate_rows_and_store_total() -> None:
    report = GiftCardsReport().parse(
        """Gift Card Bonus Report
Associate #
Name
Total Transactions
Total Qualifying Transactions
Total Transactions With GC Bonus
%Transactions W/ GC Bonus
0079555
Montejano, Mindy
75
75
16
21%
0083099
Hollister, Morgan
5
5
1
20%
0056852
Esparza, Vanessa
67
67
11
16%
0081940
Gundermann, 
Brynn
33
33
5
15%
0083125
Alvarado, Gabbie
9
9
1
11%
0075958
Pabelico, Auggie
44
44
4
9%
0075677
Perez, Natalie
33
33
2
6%
0017333
Elofson, Tom
48
48
1
2%
0067394
Ebitner, Haley
82
82
0
0%
0069809
Deckert, Rachel
1
1
0
0%
0070419
Fredberg, Danny
9
9
0
0%
0080955
Gomez, Val
3
3
0
0%
Totals
409
409
41
10%
Store Number:
From Date:
Sunday, February 01, 2026
To Date:
Saturday, February 07, 2026
1214
"""
    )

    assert report.report_type == "gift_cards"
    assert report.period_start == "2026-02-01"
    assert report.period_end == "2026-02-07"
    assert report.payload["store_number"] == "1214"
    assert report.payload["associate_rows"][0]["name"] == "Montejano, Mindy"
    assert report.payload["associate_rows"][3]["name"] == "Gundermann, Brynn"
    assert len(report.payload["associate_rows"]) == 12
    assert report.payload["store_total"]["name"] == "Store Sales"
    assert report.payload["store_total"]["metrics"]["total_transactions"] == 409
    assert report.payload["store_total"]["metrics"]["gc_bonus_transactions"] == 41
    assert report.payload["viewer"]["headers"] == ["Associate #", "Name", "Total Transactions", "Total Transactions with GC Bonus", "% Transactions w/ GC Bonus", "Missed Opportunities"]
    assert report.payload["viewer"]["rows"][0]["values"][0] == "0079555"
    assert report.payload["weekly_sales_missing"] is True


@pytest.mark.django_db
def test_gift_cards_parser_handles_flattened_live_text() -> None:
    report = GiftCardsReport().parse(
        """Associate #: 0079555
Name: Montejano, Mindy
Total Transactions: 75
Total Qualifying Transactions: 75
Total Transactions With GC Bonus: 16
%Transactions W/ GC Bonus: 21%

Gift Card Bonus Report
Store Number: 1214
From Date: Sunday, February 01, 2026
To Date: Saturday, February 07, 2026
Associate # Name Total Total Total %Transactions
Transactions Qualifying Transactions W/ GC Bonus
Transactions With GC Bonus
0079555 Montejano, Mindy 75 75 16 21%
0083099 Hollister, Morgan 5 5 1 20%
0056852 Esparza, Vanessa 67 67 11 16%
Totals 409 409 41 10%"""
    )

    assert report.report_type == "gift_cards"
    assert report.period_start == "2026-02-01"
    assert report.period_end == "2026-02-07"
    assert report.payload["store_number"] == "1214"
    assert len(report.payload["associate_rows"]) == 3
    assert report.payload["associate_rows"][0]["name"] == "Montejano, Mindy"
    assert report.payload["store_total"]["metrics"]["total_transactions"] == 409


@pytest.mark.django_db
def test_bonus_club_parser_extracts_associate_rows_and_store_total() -> None:
    report = BonusClubReport().parse(
        """Bonus Club Capture Report
Associate #
Name
Total Transactions
Transactions With Club #
Bonus Club Capture Rate
0069809
Deckert, Rachel
1
1
100%
0080955
Gomez, Val
3
3
100%
0070419
Fredberg, Danny
9
8
89%
0083125
Alvarado, Gabbie
9
8
89%
0075958
Pabelico, Auggie
44
35
80%
0083099
Hollister, Morgan
5
4
80%
0075677
Perez, Natalie
33
25
76%
0056852
Esparza, Vanessa
67
50
75%
0067394
Ebitner, Haley
82
51
62%
0081940
Gundermann, Brynn
33
20
61%
0017333
Elofson, Tom
48
29
60%
0079555
Montejano, Mindy
75
40
53%
Totals
409
274
67%
1214
Sunday, February 01, 2026
Saturday, February 07, 2026
Store Number:
From Date:
To Date:"""
    )

    assert report.report_type == "bonus_club"
    assert report.period_start == "2026-02-01"
    assert report.period_end == "2026-02-07"
    assert report.payload["store_number"] == "1214"
    assert report.payload["associate_rows"][0]["name"] == "Deckert, Rachel"
    assert report.payload["associate_rows"][11]["name"] == "Montejano, Mindy"
    assert len(report.payload["associate_rows"]) == 12
    assert report.payload["store_total"]["name"] == "Store Sales"
    assert report.payload["store_total"]["metrics"]["total_transactions"] == 409
    assert report.payload["store_total"]["metrics"]["transactions_with_club"] == 274
    assert report.payload["viewer"]["headers"] == ["Associate #", "Name", "Total Transactions", "Transactions With Club #", "Bonus Club Capture Rate"]
    assert report.payload["viewer"]["rows"][0]["values"][0] == "0069809"


def test_registry_rejects_duplicate_slugs() -> None:
    clear()
    register(DummyReport())
    with pytest.raises(ValueError, match="already registered"):
        register(DummyReport())


def test_builtin_weekly_sales_report_registers_once_and_tracks_history() -> None:
    clear()
    loaded = load_builtin_reports()

    assert loaded == ("weekly_sales", "ranking", "segments", "gift_cards", "bonus_club")
    assert tuple(report.slug for report in all_reports()) == ("weekly_sales", "ranking", "segments", "gift_cards", "bonus_club")
    assert get("gift_cards").display_name == "Gift Cards"
    assert get("bonus_club").display_name == "Bonus Club"
    assert get("segments").display_name == "Segments"
    assert history() == ("weekly_sales", "ranking", "segments", "gift_cards", "bonus_club")

    assert load_builtin_reports() == ()
    assert history() == ("weekly_sales", "ranking", "segments", "gift_cards", "bonus_club")
