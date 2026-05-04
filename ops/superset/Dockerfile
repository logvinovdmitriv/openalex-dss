ARG SUPERSET_IMAGE=apache/superset:latest
FROM ${SUPERSET_IMAGE}

USER root
RUN pip install --no-cache-dir duckdb-engine
USER superset
