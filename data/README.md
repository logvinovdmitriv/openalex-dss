# Data Directory

This repository intentionally does not store generated OpenAlex data.

The app maps the virtual `data/...` paths to the external data root:

```text
../openalex-dss-data
```

Override it with:

```bash
export OPENALEX_DSS_DATA_DIR="/absolute/path/to/openalex-dss-data"
```

Raw dumps, normalized tables, marts, reports, passports, checksums and DuckDB
warehouses belong in that external directory, not in git.
