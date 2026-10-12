# Build context is the repo root (docker-compose.yml): the detector reuses
# the gateway's context queries, which assert that no fault_* query exists.
FROM python:3.12-slim

WORKDIR /app

COPY ml/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gateway/context.py ./gateway/
COPY ml/model.py ml/detector.py ml/train.py ./ml/

WORKDIR /app/ml

CMD ["python", "detector.py"]
