# User Runbook

This runbook describes the normal operator path for building a reproducible
OpenAlex DSS analysis.

## Start The System

Install dependencies once:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r apps/api/requirements.txt
.venv/bin/pip install openalex-official
npm install
```

Start backend and frontend:

```bash
python3 scripts/run_dss.py
```

Open:

```text
UI:  http://127.0.0.1:5173
API: http://127.0.0.1:8000/api/v1
Docs: http://127.0.0.1:8000/docs
```

## Normal Workflow

1. Open `Срез`.
2. Select the OpenAlex entity level and entity identifier.
3. Resolve the slice and review the resolved entity.
4. Build the estimate and inspect expected volume, facets, and budget.
5. Build a materialization plan.
6. Run materialization after accepting the estimate and download signatures.
7. Wait until the job completes and active context points to the new `run_id`
   and `dump_id`.
8. Open `Данные` and verify that local scoped tables are present.
9. Open `Индексы` and inspect `indices` and `ratings`.
10. Create or select a cohort in `Когорты`.
11. Open `Графики` and inspect distributions, rank shifts, outliers, and
    comparisons.
12. Open `Отчеты` and download the report bundle, findings CSV, conclusion
    Markdown, and supporting exports.
13. Open `Паспорта` and verify slice, calculation, checksums, pipeline summary,
    quality report, and provenance.

## Scope Rules

All analytical reads require scope:

```text
run_id
dump_id
cohort-resolved run/dump scope
```

The active context is a UI pointer. It helps the interface select the current
run and dump, but report acceptance should still be tied to explicit `run_id`,
`dump_id`, and `report_scope_hash`.

## Operational Limits

- OpenAlex metadata quality and author disambiguation affect all downstream
  metrics.
- The system does not infer demographic attributes.
- Local indices describe authors inside the selected slice; they are not global
  author scores.
- OpenAlex API calls are used for resolving, estimates, catalogs, and targeted
  enrichment. The analytical corpus is the locally materialized dump.
- Final analysis requires an eligible dump manifest and scoped run artifacts.
- The deterministic validation fixture is a system check, not scientific
  evidence.
- Report findings and conclusion drafts support expert review; they do not
  replace domain judgment.

## Acceptance Before Handoff

Before handing a run to a user, complete the gate in
`docs/acceptance.md` and keep the validation output with the delivery notes.
