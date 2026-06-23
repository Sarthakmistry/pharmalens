FROM python:3.11-slim

WORKDIR /app

# Install dependencies from root requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the packages the compiler needs (not raw/ or wiki/ — those live on GCS)
COPY agents/    agents/
COPY reference/ reference/

COPY DataPipelines/compiler-job/entrypoint.py .

CMD ["python", "entrypoint.py"]
