# CLARION backup runner (roadmap P2.8). mariadb:11.4 already carries
# mariadb-backup + mariadb-binlog + the mariadb client; add restic / age /
# rsync / mydumper / mc on top.
FROM mariadb:11.4

ARG MC_VERSION=RELEASE.2025-04-22T22-12-26Z
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        restic age rsync mydumper ca-certificates curl cron python3; \
    curl -fsSL "https://dl.min.io/client/mc/release/linux-amd64/archive/mc.${MC_VERSION}" -o /usr/local/bin/mc; \
    chmod +x /usr/local/bin/mc; \
    rm -rf /var/lib/apt/lists/*

COPY --chmod=0755 *.sh /opt/clarion-backup/
WORKDIR /opt/clarion-backup
ENTRYPOINT ["/bin/bash", "-c"]
# The compose service overrides `command:` with the cron install, or run a
# one-off:  docker compose run --rm backup "./backup.sh weekly"
CMD ["./backup.sh daily"]
