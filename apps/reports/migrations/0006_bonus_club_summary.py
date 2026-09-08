from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0005_gift_cards_summary"),
    ]

    operations = [
        migrations.CreateModel(
            name="BonusClubSummary",
            fields=[
                (
                    "id",
                    models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
                ),
                ("fiscal_year", models.PositiveSmallIntegerField()),
                ("fiscal_week", models.PositiveSmallIntegerField()),
                ("fiscal_period_start", models.DateField(blank=True, null=True)),
                ("fiscal_period_end", models.DateField(blank=True, null=True)),
                ("raw_json", models.JSONField(blank=True, default=dict)),
                ("ai_summary", models.TextField(blank=True, default="")),
                ("ai_provider", models.CharField(blank=True, default="", max_length=64)),
                ("ai_model", models.CharField(blank=True, default="", max_length=128)),
                ("ai_payload", models.JSONField(blank=True, default=dict)),
                ("ai_error", models.TextField(blank=True, default="")),
                ("ai_generated_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "report_upload",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bonus_club_summary",
                        to="reports.reportupload",
                    ),
                ),
            ],
            options={
                "verbose_name": "bonus club summary",
                "verbose_name_plural": "bonus club summaries",
                "ordering": ["-fiscal_year", "-fiscal_week", "-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="bonusclubsummary",
            constraint=models.UniqueConstraint(
                fields=("fiscal_year", "fiscal_week"),
                name="unique_bonus_club_summary_fiscal_period",
            ),
        ),
    ]
