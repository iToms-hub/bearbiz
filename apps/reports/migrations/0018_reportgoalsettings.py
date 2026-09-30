from django.db import migrations, models
import decimal


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0017_replace_schedules_with_gantts"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReportGoalSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("singleton_key", models.PositiveSmallIntegerField(default=1, editable=False, unique=True)),
                ("gift_card_goal", models.DecimalField(decimal_places=2, default=decimal.Decimal("18.00"), max_digits=5)),
                ("bonus_club_goal", models.DecimalField(decimal_places=2, default=decimal.Decimal("80.00"), max_digits=5)),
            ],
        ),
    ]