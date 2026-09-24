FROM python:3.11-slim
WORKDIR /app
COPY server.py panelbook.html app.js styles.css /app/
RUN groupadd -r panelbook && useradd -r -g panelbook panelbook && mkdir /data && chown panelbook:panelbook /data
USER panelbook
VOLUME /data
EXPOSE 8765
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8765", "--data-dir", "/data", "--no-browser", "--secure-cookies"]
