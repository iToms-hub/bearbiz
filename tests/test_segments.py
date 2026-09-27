from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.core.models import FiscalYearSettings
from apps.reports.models import MissedOpportunityReport, SegmentReport
from apps.reports.segments import parse_segment_report, display_rows

ATTACHMENTS = Path('/home/tome/.hermes/profiles/claire/attachments')


@pytest.fixture()
def fiscal_settings(db):
    return FiscalYearSettings.objects.create(fiscal_year_start_date=date(2026, 2, 1))


def mo_report():
    return MissedOpportunityReport.objects.create(
        fiscal_year=2027, fiscal_week=33, week_end=date(2026, 9, 19), source_name='week 33.pdf',
        days=[
            {'day': 'Sun', 'missed_store_sales': '$308', 'has_missed_opportunity': True},
            {'day': 'Sat', 'missed_store_sales': '$1,078', 'has_missed_opportunity': True},
        ],
    )


def test_segment_parser_preserves_source_and_projects_requested_columns():
    parsed = parse_segment_report((ATTACHMENTS / 'week 33 saturday report.pdf').read_bytes(), 'week 33 saturday report.pdf')
    assert parsed['day'] == 'Saturday'
    assert parsed['day_date'] == '2026-09-19'
    assert len(parsed['headers']) == 38
    assert len(parsed['rows']) == 13
    assert [row['values'][0] for row in display_rows(parsed)] == ['8:00 AM', '10:00 AM', '12:00 PM', '2:00 PM', '4:00 PM', '6:00 PM', '8:00 PM', '10:00 PM']
    assert [row['values'][0] for row in display_rows(parsed) if row['highlight']] == ['2:00 PM', '4:00 PM', '6:00 PM']
    assert display_rows(parsed)[1]['values'] == ['10:00 AM', '$264', '-49.3%', '-21.5%', '12.0%', '$29.32', '18.8']
    assert display_rows(parsed)[2]['values'] == ['12:00 PM', '$973', '-22.7%', '-13.2%', '11.1%', '$49.43', '16.9']

    sunday = parse_segment_report((ATTACHMENTS / 'week 33 sunday report.pdf').read_bytes(), 'week 33 sunday report.pdf')
    sunday_rows = display_rows(sunday)
    assert not any(row['highlight'] for row in sunday_rows if row['values'][0] == '6:00 PM')
    assert all(row['values'][1] != '$0' for row in sunday_rows if row['highlight'])


@pytest.mark.django_db()
def test_segment_upload_stores_required_opportunity_days_and_renders(fiscal_settings):
    mo_report()
    client = Client()
    files = [
        SimpleUploadedFile('week 33 saturday report.pdf', (ATTACHMENTS / 'week 33 saturday report.pdf').read_bytes(), content_type='application/pdf'),
        SimpleUploadedFile('week 33 sunday report.pdf', (ATTACHMENTS / 'week 33 sunday report.pdf').read_bytes(), content_type='application/pdf'),
    ]
    response = client.post(reverse('missed-ops-segments'), {'fiscal_week': '33', 'source_files': files})
    assert response.status_code == 302
    assert SegmentReport.objects.count() == 2
    assert all(len(report.headers) == 38 and len(report.rows) == 13 for report in SegmentReport.objects.all())
    html = client.get(reverse('missed-ops-segments'), {'week': '33'}).content.decode()
    assert response.status_code == 302
    assert 'Traffic Leverage' in html
    assert 'Missed Customers' not in html
    assert 'Days still needed:' not in html
    assert 'Required days:' not in html
    assert html.count('<table') == 2
    assert '10:00 AM' in html
