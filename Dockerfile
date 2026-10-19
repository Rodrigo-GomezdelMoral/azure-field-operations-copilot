FROM python:3.12-slim AS runtime
WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 fop
COPY app ./app
COPY mcp_inventory ./mcp_inventory
COPY a2a_server ./a2a_server
COPY ops ./ops
COPY eval ./eval
COPY prompts ./prompts
USER fop
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
