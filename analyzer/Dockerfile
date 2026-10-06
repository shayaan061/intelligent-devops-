FROM python:3.12-slim

WORKDIR /analyzer

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY schemas.py runbooks.py llm.py analyzer.py ./

# Runbooks live at the repo root (../runbooks), outside this build context;
# compose mounts them read-only here.
ENV RUNBOOK_DIR=/runbooks \
    PYTHONUNBUFFERED=1

CMD ["python", "analyzer.py", "serve"]
