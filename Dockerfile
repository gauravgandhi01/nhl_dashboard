FROM node:22-bookworm AS frontend

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY config ./config
RUN mkdir -p data && python -m backend.build_seed
COPY --from=frontend /app/dist ./dist

ENV PYTHONUNBUFFERED=1
ENV NHL_DASHBOARD_DB=/tmp/dashboard.sqlite3
ENV NHL_MONEYPUCK_REFRESH_HOURS=0

CMD uvicorn backend.app:app --host 0.0.0.0 --port ${PORT}
