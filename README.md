# Bearbiz

Bearbiz is a custom BI platform for weekly report uploads, PDF extraction, dashboarding, and printable/exportable sales reporting.

**Current version:** `0.0.1`

## What Bearbiz does

- Upload one fixed-structure report at a time
- Extract data from weekly PDF reports into structured storage
- Show per-report dashboards and one combined dashboard
- Export selected report data to printable PDF outputs
- Keep the runtime small: one app container plus Postgres
- Allow new report types to be added later without rewiring the app

## Getting started

1. Optional: copy the sample environment file if you want to override defaults:

   ```bash
   cp .env.example .env
   ```

2. Start the app:

   ```bash
   docker compose up --build
   ```

3. Open:
   - `http://localhost:8000/health/`
   - `http://localhost:8000/admin/`

## Project rules

- Semantic versioning from the start
- One report at a time
- Shared core + per-report modules
- Kanban-driven tasking

## Repository layout

- `bearbiz/` — Django project config
- `apps/core/` — shared application pieces
- `apps/reports/` — report contracts and registry
- `docs/` — versioning and tasking notes
