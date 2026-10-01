FROM i386/debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV WINEDEBUG=-all
ENV WINEPREFIX=/root/.wine

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        wine \
        ffmpeg \
        python3 \
        python3-flask \
        ca-certificates \
        curl \
        procps && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

CMD ["bash", "/app/entrypoint.sh"]
