from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reports", "0016_segmentreportimport_segmentreport")]

    operations = [
        migrations.DeleteModel(name="ManagerScheduleWeek"),
        migrations.DeleteModel(name="ManagerScheduleImport"),
        migrations.CreateModel(
            name="GanttImport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_name", models.CharField(max_length=255)),
                ("parse_status", models.CharField(choices=[("pending", "Pending"), ("parsed", "Parsed"), ("failed", "Failed")], default="pending", max_length=16)),
                ("parse_error", models.TextField(blank=True)),
                ("fiscal_year", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("fiscal_week", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("day_of_week", models.CharField(blank=True, max_length=12)),
                ("day_date", models.DateField(blank=True, null=True)),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("parsed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ["-uploaded_at", "-id"]},
        ),
        migrations.CreateModel(
            name="GanttReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fiscal_year", models.PositiveSmallIntegerField()),
                ("fiscal_week", models.PositiveSmallIntegerField()),
                ("day_of_week", models.CharField(max_length=12)),
                ("day_date", models.DateField()),
                ("week_end", models.DateField()),
                ("source_name", models.CharField(max_length=255)),
                ("time_slots", models.JSONField(blank=True, default=list)),
                ("employees", models.JSONField(blank=True, default=list)),
                ("imported_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Gantt report",
                "verbose_name_plural": "Gantt reports",
                "ordering": ["-fiscal_year", "-fiscal_week", "day_date"],
            },
        ),
        migrations.AddConstraint(
            model_name="ganttreport",
            constraint=models.UniqueConstraint(fields=("fiscal_year", "fiscal_week", "day_of_week"), name="unique_gantt_report_period_day"),
        ),
    ]
