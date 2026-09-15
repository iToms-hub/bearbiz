from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_replace_ai_api_key_env_var"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReviewTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("layout", models.JSONField(default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("name",)},
        ),
    ]
