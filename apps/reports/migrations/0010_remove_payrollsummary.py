from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0009_alter_reportupload_parse_status"),
    ]

    operations = [
        migrations.RunSQL(
            sql='DROP TABLE IF EXISTS "reports_payrollsummary"',
            reverse_sql=None,
            state_operations=[
                migrations.DeleteModel(
                    name="PayrollSummary",
                ),
            ],
        ),
    ]
