from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion

from apps.reports.models import report_upload_path


class Migration(migrations.Migration):
    initial = True

    dependencies: list[tuple[str, str]] = []

    operations = [
        migrations.CreateModel(
            name="ReportUpload",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("source_file", models.FileField(upload_to=report_upload_path)),
                ("source_name", models.CharField(max_length=255)),
                (
                    "parse_status",
                    models.CharField(
                        choices=[("pending", "Pending"), ("parsed", "Parsed"), ("failed", "Failed")],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("parse_error", models.TextField(blank=True)),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("parsed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "verbose_name": "report upload",
                "verbose_name_plural": "report uploads",
                "ordering": ["-uploaded_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="WeeklySalesSummary",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("fiscal_year", models.PositiveSmallIntegerField()),
                ("fiscal_week", models.PositiveSmallIntegerField()),
                ("fiscal_period_start", models.DateField(blank=True, null=True)),
                ("fiscal_period_end", models.DateField(blank=True, null=True)),
                ("raw_json", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "report_upload",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="weekly_sales_summary",
                        to="reports.reportupload",
                    ),
                ),
            ],
            options={
                "verbose_name": "weekly sales summary",
                "verbose_name_plural": "weekly sales summaries",
                "ordering": ["-fiscal_year", "-fiscal_week", "-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="weeklysalessummary",
            constraint=models.UniqueConstraint(
                fields=("fiscal_year", "fiscal_week"),
                name="unique_weekly_sales_summary_fiscal_period",
            ),
        ),
    ]
