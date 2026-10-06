from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0008_reviewtemplate_subtitle")]

    operations = [
        migrations.CreateModel(
            name="BackupConfirmationToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token_hash", models.CharField(max_length=64, unique=True)),
                ("purpose", models.CharField(max_length=32)),
                ("consumed_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "indexes": [models.Index(fields=["purpose", "consumed_at"], name="core_backup_purpose_89979b_idx")],
            },
        ),
    ]