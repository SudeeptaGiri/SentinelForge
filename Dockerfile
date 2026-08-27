# Description: Container spec for running the SentinelForge agent system on Agent Engine.
# Need: Vertex AI Agent Engine deploys the agent as a container image; a reproducible
#       build is required for consistent runtime behavior across environments.
# Motive: Provide a minimal, secure base image that installs only declared
#         dependencies and runs the FastAPI/Agent Engine entrypoint as a non-root user.

FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir poetry && poetry config virtualenvs.create false \
    && poetry install --no-root --only main

COPY . .

RUN useradd -m appuser
USER appuser

CMD ["python", "-m", "src.main"]
