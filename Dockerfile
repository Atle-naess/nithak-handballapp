FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=10000
EXPOSE 10000
CMD ["sh", "-c", "python -c 'from app import init; init()' && waitress-serve --listen=0.0.0.0:${PORT:-10000} app:app"]
