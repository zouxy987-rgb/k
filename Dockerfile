FROM python:3.12-slim
WORKDIR /app
COPY gate_xauusd_cfd_audit.py cloud_runner.py indicators.py abc_strategy.py ./
ENV PYTHONUNBUFFERED=1
VOLUME ["/output", "/state"]
CMD ["python", "cloud_runner.py", "--out-dir", "/output", "--state-dir", "/state", "--send-mail"]
