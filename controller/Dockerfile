FROM python:3.13-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

EXPOSE 8100
CMD ["uvicorn", "scalpel_controller.app:app", "--host", "0.0.0.0", "--port", "8100"]
