from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("reports", "0007_payrollsummary")]
    operations = [migrations.CreateModel(
        name="PartiesSummary",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("fiscal_year", models.PositiveSmallIntegerField()),
            ("fiscal_week", models.PositiveSmallIntegerField()),
            ("rows", models.JSONField(blank=True, default=list)),
            ("raw_json", models.JSONField(blank=True, default=dict)),
            ("parse_version", models.PositiveSmallIntegerField(default=1)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("report_upload", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="parties_summary", to="reports.reportupload")),
        ],
        options={"ordering": ["fiscal_year", "fiscal_week", "id"]},
    )]