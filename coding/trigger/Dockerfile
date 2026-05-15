FROM python:3.12-alpine
# hadolint ignore=DL3018
RUN apk add --no-cache docker-cli docker-cli-compose
COPY server.py /trigger/server.py
CMD ["python3", "/trigger/server.py"]
