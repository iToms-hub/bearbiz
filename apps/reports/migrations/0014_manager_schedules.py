from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0013_productreport_productitem"),
    ]

    operations = [
        migrations.CreateModel(
            name="ManagerScheduleImport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_name", models.CharField(max_length=255)),
                ("parse_status", models.CharField(choices=[("pending", "Pending"), ("parsed", "Parsed"), ("failed", "Failed"), ("conflict", "Conflict")], default="pending", max_length=16)),
                ("parse_error", models.TextField(blank=True)),
                ("week_count", models.PositiveSmallIntegerField(default=0)),
                ("periods", models.JSONField(blank=True, default=list)),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("parsed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "ordering": ["-uploaded_at", "-id"],
                "verbose_name": "manager schedule import",
                "verbose_name_plural": "manager schedule imports",
            },
        ),
        migrations.CreateModel(
            name="ManagerScheduleWeek",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fiscal_year", models.PositiveSmallIntegerField()),
                ("fiscal_month", models.PositiveSmallIntegerField()),
                ("fiscal_week", models.PositiveSmallIntegerField()),
                ("week_start", models.DateField()),
                ("week_end", models.DateField()),
                ("source_name", models.CharField(max_length=255)),
                ("rows", models.JSONField(blank=True, default=list)),
                ("imported_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["fiscal_year", "fiscal_week"],
                "verbose_name": "manager schedule week",
                "verbose_name_plural": "manager schedule weeks",
            },
        ),
        migrations.AddConstraint(
            model_name="managerscheduleweek",
            constraint=models.UniqueConstraint(
                fields=("fiscal_year", "fiscal_week"),
                name="unique_manager_schedule_fiscal_period",
            ),
        ),
    ]
