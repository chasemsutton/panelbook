FROM python:3.11-slim
WORKDIR /app
COPY program/server.py program/panelbook.html program/app.js program/styles.css /app/program/
RUN groupadd -r panelbook && useradd -r -g panelbook panelbook && mkdir /data && chown panelbook:panelbook /data
USER panelbook
VOLUME /data
EXPOSE 8765
CMD ["python", "program/server.py", "--host", "0.0.0.0", "--port", "8765", "--data-dir", "/data", "--no-browser", "--secure-cookies"]
