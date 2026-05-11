# Real OpenAlex Slice Acceptance

This gate complements the deterministic fixture validation. It is intentionally
opt-in because it consumes OpenAlex quota, disk and wall-clock time.

## Estimate-Only Benchmark

```bash
scripts/benchmark_real_slice.py \
  --subject-level subfield \
  --subject-id 2604 \
  --subject-name "Applied Mathematics" \
  --from-date 2020-01-01 \
  --to-date 2024-12-31 \
  --work-type article \
  --source-strategy openalex_api \
  --out runs_real_benchmark_estimate.json
```

Expected checks:

- `decision.can_execute` is true or the reason is explicitly actionable.
- `storage_estimate.recommended_free_space_bytes` is present.
- estimate includes selected/full payload, CLI/API or snapshot strategy notes.

## Live Download Benchmark

Run only after confirming available disk and OpenAlex API key:

```bash
OPENALEX_API_KEY=... scripts/benchmark_real_slice.py \
  --subject-level subfield \
  --subject-id 2604 \
  --subject-name "Applied Mathematics" \
  --from-date 2020-01-01 \
  --to-date 2024-12-31 \
  --work-type article \
  --source-strategy openalex_api \
  --download \
  --out runs_real_benchmark_download.json
```

Acceptance facts to record in the report:

- `n_works`, `records_expected`, `records_downloaded`, `records_count_verified`.
- `download_elapsed_seconds`, raw size, table size, cache size.
- estimate-vs-actual ratio and calibration entry.
- backfill status for truncated authorships.
- chart readiness summary.
- whether final eligibility is `final_reproducible`, `pilot_ready`, `exploratory`, or `blocked`.

The benchmark is not a scientific claim by itself; it validates that the DSS can
run the full backend-first pipeline on a real OpenAlex corpus slice.
