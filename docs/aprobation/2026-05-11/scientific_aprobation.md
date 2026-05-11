# Scientific Approbation Run: Applied Mathematics 2020-2024

Date: 2026-05-11
Repository HEAD before this run: `5f56aa1`
Real data directory: `/Users/logvinovdmitriv/University/Диплом/openalex-dss-data`

This document records the real OpenAlex approbation run used to verify that the
project is not limited to synthetic fixtures. API secrets were passed only
through the runtime environment and are not stored in this repository.

## Scope

The run materialized a real OpenAlex Works slice with the following scope:

- Entity: Applied Mathematics subfield, `primary_topic.subfield.id:2604`
- Publication dates: `2020-01-01` through `2024-12-31`
- Work type: `article`
- Exclusions: `is_retracted:false`, `is_paratext:false`, `is_xpac:false`
- Materialization strategy: `openalex_api` cursor download
- Baseline fraction mode: `strict_authors_count`

The exact estimate, download, materialization, and analysis manifests are stored
in this directory:

- `estimate.json`
- `download.json`
- `materialization.json`
- `summary.json`
- `baseline_bundle_manifest.json`
- `extension_iupv_s_bundle_manifest.json`
- `sha256_manifest.txt`

## Commands

The commands below are shown with the API key redacted.

```bash
OPENALEX_API_KEY='***' .venv/bin/python scripts/benchmark_real_slice.py \
  --subject-level subfield \
  --subject-id 2604 \
  --subject-name "Applied Mathematics" \
  --from-date 2020-01-01 \
  --to-date 2024-12-31 \
  --work-type article \
  --source-strategy openalex_api \
  --out runs_real_benchmark_estimate.json

OPENALEX_API_KEY='***' .venv/bin/python scripts/benchmark_real_slice.py \
  --subject-level subfield \
  --subject-id 2604 \
  --subject-name "Applied Mathematics" \
  --from-date 2020-01-01 \
  --to-date 2024-12-31 \
  --work-type article \
  --source-strategy openalex_api \
  --download \
  --out runs_real_benchmark_download.json

.venv/bin/python scripts/export_analysis_bundle.py \
  --run-id applied_math_2020_2024_v1 \
  --dump-id dump_685cee7bcbf4912b \
  --fraction-mode strict_authors_count \
  --metrics p,c,c_frac,h,i10,g \
  --baseline h \
  --out /Users/logvinovdmitriv/University/Диплом/analysis_bundle_baseline

.venv/bin/python scripts/export_analysis_bundle.py \
  --run-id applied_math_2020_2024_v1 \
  --dump-id dump_685cee7bcbf4912b \
  --fraction-mode strict_authors_count \
  --metrics p,c,c_frac,h,i10,g,iupv_s \
  --baseline h \
  --out /Users/logvinovdmitriv/University/Диплом/analysis_bundle_extension_iupv_s
```

The materialization step used `pipeline.import_local_file` with
`import_mode=final_reproducible` and the download manifest produced by the API
cursor provider.

## Results

Identifiers:

- `dump_id`: `dump_685cee7bcbf4912b`
- `run_id`: `applied_math_2020_2024_v1`
- Raw JSONL SHA-256:
  `685cee7bcbf4912b9959637cfe831da3b924416798267d8e8da436545eae3d12`

Download and eligibility:

- Estimated works: `108691`
- Downloaded works: `108691`
- Records delta: `0`
- `records_count_verified`: `true`
- `scientific_completeness`: `complete`
- `allowed_for_final_analysis`: `true`
- Eligibility status: `final`
- Signature checks: estimate, accepted estimate, and download signatures verified

Materialized table counts:

| Table | Rows |
| --- | ---: |
| `works` | 108691 |
| `authorships` | 276179 |
| `work_topics` | 314836 |
| `author_institutions` | 255065 |
| `author_countries` | 226027 |
| `author_work` | 777369 |
| `indices` | 359343 |
| `ratings` | 6108831 |

Strict baseline authors:

- `strict_authors_count` authors: `119781`
- Baseline analysis authors: `119781`
- Extension analysis authors: `119781`

Quality checks:

- Truncated works detected: `0`
- Missing primary topic works: `0`
- Retracted works after local guard: `0`
- Paratext works after local guard: `0`
- XPAC works after local guard: `0`
- Null author ID authorships: `16831`
- Duplicate author ID authorships: `451`
- Authorship truncation flags in authorships: `0`
- Author count mismatch flags: `0`

IUPV-S extension checks:

- `ratings` contains `metric_name=iupv_s`: `true`
- Positive `iupv_s` authors in strict mode: `74424`
- Violations of `rfi_log_frac <= 0 => iupv_s = 0`: `0`
- Baseline metrics present in ratings: `p`, `c`, `c_frac`, `h`, `i10`, `g`

## Analysis Bundles

Baseline bundle:

- Path: `/Users/logvinovdmitriv/University/Диплом/analysis_bundle_baseline`
- Analysis ID: `analysis_9bfdd540e884935f`
- Filters hash: `9bfdd540e884935f3dbe29053be2412d`
- Metrics: `p`, `c`, `c_frac`, `h`, `i10`, `g`
- Data scope: `full_filtered_slice`
- Findings: `30`

Extension bundle:

- Path: `/Users/logvinovdmitriv/University/Диплом/analysis_bundle_extension_iupv_s`
- Analysis ID: `analysis_5b4ee7361a0c49c0`
- Filters hash: `5b4ee7361a0c49c0fba1db6d0243bc0f`
- Metrics: `p`, `c`, `c_frac`, `h`, `i10`, `g`, `iupv_s`
- Data scope: `full_filtered_slice`
- Findings: `37`

## Methodological Notes

Baseline and extension are deliberately separated:

- Baseline: `P`, `C`, `C_frac`, `h`, `i10`, `g`
- Extension: `IUPV-S` and other diagnostic/research metrics

The API cursor run does not request `authors_count` through Works `select`,
because OpenAlex rejects it as an invalid select field for list requests.
Normalization therefore keeps strict-count logic defensive: if OpenAlex provides
a reported count in the record it is used; otherwise strict weights fall back to
observed authorship count. This real run detected no truncated works and no
author-count mismatch flags, so the fallback did not block final eligibility.

The approbation verifies the software pipeline, reproducibility gates, scoped
backend analytics, and report/export generation on a real OpenAlex slice. It is
not, by itself, a peer-reviewed scientific conclusion about Applied Mathematics;
the substantive interpretation belongs in the thesis/report built from the
recorded analysis bundles.

## Verdict

The scientific approbation of the software complex was completed on a real
OpenAlex slice. The run produced a complete dump, verified signatures,
materialized local tables, final eligibility, baseline analysis artifacts,
IUPV-S extension artifacts, report bundles, and checksums.

## Repository Acceptance

After the real run, the repository acceptance gate was executed successfully:

```text
git diff --check
pytest selected acceptance suite: 217 passed, 3 subtests passed
pytest full suite: 304 passed, 3 subtests passed
npm run build:web: passed
npm run test:e2e:web: 3 passed
python scripts/validate_scientometric_dss.py --reset: status ok
```

The deterministic validation fixture remains explicitly marked as not suitable
for final scientific conclusions; the real OpenAlex run recorded above is the
final-eligibility approbation slice.
