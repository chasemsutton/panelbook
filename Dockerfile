FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PANELBOOK_PUBLIC_SCHEME=http
WORKDIR /app
COPY program/server.py program/panelbook.html program/app.js program/styles.css /app/program/
# A fixed UID lets host-side backups and migrations set ownership without
# looking it up. A new named volume copies /data's ownership from the image.
RUN groupadd -r -g 10001 panelbook && useradd -r -u 10001 -g panelbook panelbook && mkdir /data && chown panelbook:panelbook /data
USER panelbook
VOLUME /data
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/status', timeout=3).close()"
CMD ["python", "program/server.py", "--host", "0.0.0.0", "--port", "8765", "--data-dir", "/data", "--no-browser"]
