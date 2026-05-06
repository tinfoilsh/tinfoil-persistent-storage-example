FROM python:3.13-slim

WORKDIR /app

COPY container/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY container/ ./

EXPOSE 8080

ENTRYPOINT ["python", "-u", "sim.py"]
