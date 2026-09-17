from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0010_remove_payrollsummary"),
    ]

    operations = [
        migrations.CreateModel(
            name="PayrollWeek",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fiscal_year", models.PositiveSmallIntegerField()),
                ("fiscal_month", models.PositiveSmallIntegerField()),
                ("fiscal_week", models.PositiveSmallIntegerField()),
                ("sales_plan", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("trend_percent", models.DecimalField(blank=True, decimal_places=2, max_digits=7, null=True)),
                ("sun", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("mon", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("tue", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("wed", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("thu", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("fri", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("sat", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("labor_calculator_target_hours", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "payroll week",
                "verbose_name_plural": "payroll weeks",
                "ordering": ["fiscal_year", "fiscal_week"],
            },
        ),
        migrations.AddConstraint(
            model_name="payrollweek",
            constraint=models.UniqueConstraint(fields=("fiscal_year", "fiscal_week"), name="unique_payroll_week"),
        ),
    ]
