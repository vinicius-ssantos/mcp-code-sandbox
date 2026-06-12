FROM eclipse-temurin:25-jdk-jammy@sha256:7bb4493421ff8fe7d0361d0518e5abf0026fc6ac774ecdf28bb6b90d4fd4c4f8

RUN useradd --create-home --shell /usr/sbin/nologin sandbox \
    && mkdir -p /workspace \
    && chown sandbox:sandbox /workspace

WORKDIR /workspace
USER sandbox
