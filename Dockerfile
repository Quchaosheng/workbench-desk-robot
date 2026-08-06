FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WORKBENCH_OFFLINE=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    PATH=/opt/workbench-venv/bin:$PATH

RUN printf 'Acquire::Retries "10";\nAcquire::http::Timeout "120";\nAcquire::https::Timeout "120";\n' \
        > /etc/apt/apt.conf.d/80-workbench-retries \
    && sed -i 's/noble noble-updates noble-backports/noble noble-updates/' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::Retries=10 update \
    && apt-get install -y --no-install-recommends ca-certificates curl python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/workbench-venv

WORKDIR /app
COPY . /app
RUN python -m pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 workbench \
    && chown -R workbench:workbench /app

USER workbench
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:8080/healthz > /dev/null || exit 1

CMD ["python", "-m", "workbench_backend.server", "--host", "0.0.0.0", "--port", "8080"]
