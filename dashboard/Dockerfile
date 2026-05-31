# odoo_metrics_exporter — small Prometheus exporter for Odoo-specific metrics
# that no off-the-shelf exporter provides: worker settings, filestore size,
# mail throughput, queue-job and cron health.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

# du(1) for filestore sizing is part of coreutils (already present in slim).
COPY exporter/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY exporter/app.py /app/app.py
WORKDIR /app

EXPOSE 9333
CMD ["python", "/app/app.py"]
