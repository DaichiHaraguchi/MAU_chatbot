FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PATH="/root/.cargo/bin:/root/.local/bin:${PATH}"
ENV UV_SYSTEM_PYTHON=1

RUN apt-get update && apt-get install -y \
    curl wget ca-certificates python3.11 python3.11-dev \
    && ln -s /usr/bin/python3.11 /usr/local/bin/python3 \
    && curl https://sh.rustup.rs -sSf | sh -s -- -y \
    && curl -Ls https://astral.sh/uv/install.sh | bash \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
COPY pyproject.toml .
COPY uv.lock .

# sync しない（後で run 時にやる）
CMD ["bash"]
