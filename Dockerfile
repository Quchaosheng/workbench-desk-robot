FROM ubuntu@sha256:678c6550cc43645e08669028bc177f50be4e7c5b8cca677067b1914d4afc7a03

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WORKBENCH_OFFLINE=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
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
COPY pyproject.toml README.md README.zh-CN.md LICENSE NOTICE ./
COPY libs/application ./libs/application
COPY libs/contracts ./libs/contracts
COPY libs/hardware ./libs/hardware
COPY libs/kernel ./libs/kernel
COPY services/agent_runtime ./services/agent_runtime
COPY services/backend ./services/backend
COPY services/world_model ./services/world_model
COPY firmware/virtual_mcu ./firmware/virtual_mcu
RUN --mount=type=cache,target=/root/.cache/pip python -m pip install --no-compile . \
    && useradd --create-home --uid 10001 workbench \
    && chown -R workbench:workbench /app
COPY . /app
RUN chown -R workbench:workbench /app

USER workbench
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:8080/healthz > /dev/null || exit 1

CMD ["python", "-m", "workbench_backend.server", "--host", "0.0.0.0", "--port", "8080"]
