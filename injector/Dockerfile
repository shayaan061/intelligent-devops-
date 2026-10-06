FROM python:3.12-slim

WORKDIR /injector

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY injector.py web.py ./
COPY static ./static

ENTRYPOINT ["python", "injector.py"]
CMD ["list"]
