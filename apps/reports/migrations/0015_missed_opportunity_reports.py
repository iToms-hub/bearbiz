from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reports", "0014_manager_schedules")]

    operations = [
        migrations.CreateModel(
            name="MissedOpportunityImport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_name", models.CharField(max_length=255)),
                ("parse_status", models.CharField(choices=[("pending", "Pending"), ("parsed", "Parsed"), ("failed", "Failed")], default="pending", max_length=16)),
                ("parse_error", models.TextField(blank=True)),
                ("fiscal_year", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("fiscal_week", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("week_end", models.DateField(blank=True, null=True)),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("parsed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ["-uploaded_at", "-id"]},
        ),
        migrations.CreateModel(
            name="MissedOpportunityReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fiscal_year", models.PositiveSmallIntegerField()),
                ("fiscal_week", models.PositiveSmallIntegerField()),
                ("week_end", models.DateField()),
                ("source_name", models.CharField(max_length=255)),
                ("days", models.JSONField(blank=True, default=list)),
                ("total", models.JSONField(blank=True, default=dict)),
                ("target", models.JSONField(blank=True, default=dict)),
                ("imported_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "missed opportunity report",
                "verbose_name_plural": "missed opportunity reports",
                "ordering": ["-fiscal_year", "-fiscal_week"],
            },
        ),
        migrations.AddConstraint(
            model_name="missedopportunityreport",
            constraint=models.UniqueConstraint(fields=("fiscal_year", "fiscal_week"), name="unique_missed_opportunity_fiscal_period"),
        ),
    ]
