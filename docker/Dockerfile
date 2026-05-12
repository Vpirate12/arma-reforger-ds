FROM cm2network/steamcmd:root

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        libsdl2-2.0-0 \
        python3 \
        jq && \
    rm -rf /var/lib/apt/lists/*

ENV DATA_DIR="/serverdata"
ENV SERVER_DIR="${DATA_DIR}/serverfiles"

RUN mkdir -p ${SERVER_DIR} ${DATA_DIR}/addons && \
    chown -R steam:steam ${DATA_DIR}

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 2001/udp 17777/udp 19999/tcp

ENTRYPOINT ["/entrypoint.sh"]
