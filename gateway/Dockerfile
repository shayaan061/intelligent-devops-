FROM python:3.12-slim

WORKDIR /gateway

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY app.py incidents.py context.py store.py ./

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
