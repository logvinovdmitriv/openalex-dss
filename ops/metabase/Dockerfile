FROM eclipse-temurin:21-jre-jammy

ARG METABASE_VERSION=0.56.9
ARG METABASE_DUCKDB_DRIVER_VERSION=1.4.1.1

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app /plugins \
  && curl -fsSL "https://downloads.metabase.com/v${METABASE_VERSION}/metabase.jar" -o /app/metabase.jar \
  && curl -fsSL "https://github.com/MotherDuck-Open-Source/metabase_duckdb_driver/releases/download/${METABASE_DUCKDB_DRIVER_VERSION}/duckdb.metabase-driver.jar" -o /plugins/duckdb.metabase-driver.jar

ENV MB_PLUGINS_DIR=/plugins
ENV MB_DB_FILE=/metabase-data/metabase.db

EXPOSE 3000
CMD ["java", "-jar", "/app/metabase.jar"]
