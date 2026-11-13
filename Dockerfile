FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOUNDBROWSER_DATABASE=/data/houndbrowser.sqlite3
WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY requirements-runtime.lock ./
COPY src ./src
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 ca-certificates && rm -rf /var/lib/apt/lists/* && pip install --no-cache-dir --upgrade 'pip>=26.2' && pip install --no-cache-dir -r requirements-runtime.lock && pip install --no-cache-dir --no-deps . && python -m playwright install --with-deps chromium && useradd --uid 10001 --create-home browser && mkdir /data && chown browser:browser /data && chmod -R a+rX /app /root/.cache/ms-playwright && cp -r /root/.cache/ms-playwright /opt/playwright && chmod -R a+rX /opt/playwright
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
USER browser
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=2)"
CMD ["houndbrowser", "serve", "--host", "0.0.0.0", "--port", "8080"]
