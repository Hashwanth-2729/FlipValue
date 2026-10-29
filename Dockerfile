# FlipValue API image for Google Cloud Run (the website is deployed separately to Firebase Hosting).
# Serves /api/v1 (developer API), /v1 (partner), /api (website, accounts), /admin/api, /health, /ready, /docs. Same image runs migrations as a Cloud Run Job.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src \
    FLIPVALUE_ENV=production \
    FLIPVALUE_TRUST_PROXY=true \
    PORT=8080

WORKDIR /app
RUN useradd --create-home --uid 10001 flipvalue

COPY requirements.txt requirements-deploy.txt ./
RUN pip install -r requirements-deploy.txt

# Application code and the resources it needs at runtime: Alembic migrations (inside src/) and the device catalogue.
# Synthetic data is included for development-mode staging only; production refuses to use it.
COPY src/ src/
COPY data/catalogue/ data/catalogue/
COPY data/estimates/ data/estimates/
COPY data/mock/ data/mock/

USER flipvalue
EXPOSE 8080
# Binds 0.0.0.0:$PORT (Cloud Run sets PORT). Migrations are NOT run here; see DEPLOYMENT.md (Cloud Run Job).
CMD ["python", "-m", "flipvalue", "serve"]
