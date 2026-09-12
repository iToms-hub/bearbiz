from django.db import migrations, models


def clear_legacy_environment_variable_names(apps, schema_editor):
    """Never reinterpret a stored environment variable name as a raw secret."""
    apps.get_model("core", "AIIntegrationSettings").objects.update(api_key="")


class Migration(migrations.Migration):
    dependencies = [("core", "0005_fiscalyearsettings_fiscal_year_start_date_and_more")]

    operations = [
        migrations.AddField(
            model_name="aiintegrationsettings",
            name="api_key",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.RunPython(clear_legacy_environment_variable_names, migrations.RunPython.noop),
        migrations.RemoveField(model_name="aiintegrationsettings", name="api_key_env_var"),
    ]
