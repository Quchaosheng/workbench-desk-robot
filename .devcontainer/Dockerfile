FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN printf 'Acquire::Retries "10";\nAcquire::http::Timeout "120";\nAcquire::https::Timeout "120";\n' \
        > /etc/apt/apt.conf.d/80-workbench-retries \
    && sed -i 's/noble noble-updates noble-backports/noble noble-updates/' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::Retries=10 update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        make \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
