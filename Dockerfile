FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /opt/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY init-letsencrypt.sh /usr/local/bin/init-letsencrypt.sh
COPY obtain_initial_cert.sh /usr/local/bin/obtain_initial_cert.sh
RUN chmod +x /usr/local/bin/entrypoint.sh \
    /usr/local/bin/init-letsencrypt.sh \
    /usr/local/bin/obtain_initial_cert.sh \
    && mkdir -p /opt/app/reports/dear_cost_sync /opt/app/media /opt/app/static/static_root

EXPOSE 5000

CMD ["entrypoint.sh"]
