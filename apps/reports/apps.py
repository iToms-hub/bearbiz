from django.apps import AppConfig


class ReportsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reports"

    def ready(self) -> None:
        from .modules import load_builtin_reports, load_parties_report

        load_builtin_reports()
        load_parties_report()
