FROM python:3.12-slim
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY requirements*.txt .
RUN python -m pip --disable-pip-version-check install --no-cache-dir --no-deps -r requirements-bootstrap.txt \
    && python -m pip install --no-cache-dir -r requirements.txt
COPY . /app
RUN useradd --uid 10001 --create-home homemovies
USER homemovies
EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "60", "app:create_runtime_app()"]
