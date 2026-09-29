FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# LightGBM needs the OpenMP runtime on Debian-based images.
RUN apt-get update && apt-get install --no-install-recommends -y libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-app.txt ./
RUN python -m pip install --no-cache-dir -r requirements-app.txt

COPY app ./app
COPY src ./src

RUN groupadd --gid 10001 shop && useradd --uid 10001 --gid shop --home-dir /app --no-create-home shop \
    && mkdir -p /app/data/app && chown -R shop:shop /app/data/app
USER shop

EXPOSE 8000
CMD ["python", "-m", "app.server", "--host", "0.0.0.0", "--port", "8000"]
