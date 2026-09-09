FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        ghostscript \
        gnupg \
        libcairo2 \
        libffi8 \
        libgdk-pixbuf-2.0-0 \
        libglib2.0-0 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpq-dev \
        poppler-utils \
        qpdf \
        shared-mime-info \
        tesseract-ocr \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        | gpg --dearmor -o /usr/share/keyrings/postgresql-archive-keyring.gpg \
    && . /etc/os-release \
    && printf 'deb [signed-by=/usr/share/keyrings/postgresql-archive-keyring.gpg] https://apt.postgresql.org/pub/repos/apt %s-pgdg main\n' "$VERSION_CODENAME" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md manage.py /app/
COPY bearbiz /app/bearbiz
COPY apps /app/apps

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
