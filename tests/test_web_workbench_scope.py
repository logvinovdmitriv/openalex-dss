from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WebWorkbenchScopeTests(unittest.TestCase):
    def test_effective_ui_scope_does_not_mix_explicit_and_active_context(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node is not available")
        esbuild_check = subprocess.run(
            ["node", "-e", "import('esbuild').catch(() => process.exit(1))"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if esbuild_check.returncode != 0:
            self.skipTest("esbuild is not available")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            entry = tmp_path / "scope_entry.ts"
            out = tmp_path / "scope_entry.mjs"
            entry.write_text(
                textwrap.dedent(
                    f"""
                    import {{ effectiveUiScope }} from {json.dumps(str(ROOT / "apps/web/src/workbench.ts"))};

                    const cases = [
                      [
                        "explicit run only does not borrow active dump",
                        {{
                          runId: "run_explicit",
                          activeContext: {{ active_run_id: "run_active", active_dump_id: "dump_active" }},
                        }},
                        {{ runId: "run_explicit", dumpId: "", source: "explicit" }},
                      ],
                      [
                        "explicit dump only does not borrow active run",
                        {{
                          dumpId: "dump_explicit",
                          activeContext: {{ active_run_id: "run_active", active_dump_id: "dump_active" }},
                        }},
                        {{ runId: "", dumpId: "dump_explicit", source: "explicit" }},
                      ],
                      [
                        "no explicit uses active context",
                        {{
                          activeContext: {{ active_run_id: "run_active", active_dump_id: "dump_active" }},
                        }},
                        {{ runId: "run_active", dumpId: "dump_active", source: "active_context" }},
                      ],
                      ["no explicit and no active context returns none", {{}}, {{ runId: "", dumpId: "", source: "none" }}],
                    ];

                    for (const [name, input, expected] of cases) {{
                      const actual = effectiveUiScope(input);
                      if (JSON.stringify(actual) !== JSON.stringify(expected)) {{
                        throw new Error(`${{name}}: expected ${{JSON.stringify(expected)}}, got ${{JSON.stringify(actual)}}`);
                      }}
                    }}
                    """
                ),
                encoding="utf-8",
            )

            build = subprocess.run(
                [
                    "node",
                    "-e",
                    (
                        "import('esbuild').then(({build}) => "
                        f"build({{entryPoints:[{json.dumps(str(entry))}], bundle:true, platform:'node', "
                        f"format:'esm', outfile:{json.dumps(str(out))}}}))"
                    ),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(build.returncode, 0, build.stderr)

            result = subprocess.run(
                ["node", str(out)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_slice_payload_normalizes_full_openalex_subject_url(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node is not available")
        esbuild_check = subprocess.run(
            ["node", "-e", "import('esbuild').catch(() => process.exit(1))"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if esbuild_check.returncode != 0:
            self.skipTest("esbuild is not available")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            entry = tmp_path / "slice_payload_entry.ts"
            out = tmp_path / "slice_payload_entry.mjs"
            entry.write_text(
                textwrap.dedent(
                    f"""
                    import {{ buildSliceDefinitionPayload }} from {json.dumps(str(ROOT / "apps/web/src/workbench.ts"))};

                    const payload = buildSliceDefinitionPayload({{
                      subject_level: "topic",
                      subject_id: "https://openalex.org/T10260",
                      subject_name: "Software Engineering Research",
                      filter_mode: "primary_topic",
                      keyword_id: "",
                      keyword_name: "",
                      text_search_query: "",
                      author_id: "",
                      author_name: "",
                      author_orcid: "",
                      institution_id: "",
                      institution_name: "",
                      institution_ror: "",
                      source_id: "",
                      source_name: "",
                      source_type: "",
                      language: "",
                      open_access_is_oa: "",
                      has_abstract: "",
                      min_cited_by_count: "",
                      doi: "",
                      affiliation_mode: "historical",
                      country_code: "",
                      from_publication_date: "2021-01-01",
                      to_publication_date: "2026-12-31",
                      work_type: "",
                    }});

                    if (payload.entity_id_short !== "T10260") {{
                      throw new Error(`expected short topic id, got ${{payload.entity_id_short}}`);
                    }}
                    if (payload.entity_id_full !== "https://openalex.org/T10260") {{
                      throw new Error(`expected canonical topic URL, got ${{payload.entity_id_full}}`);
                    }}
                    """
                ),
                encoding="utf-8",
            )

            build = subprocess.run(
                [
                    "node",
                    "-e",
                    (
                        "import('esbuild').then(({build}) => "
                        f"build({{entryPoints:[{json.dumps(str(entry))}], bundle:true, platform:'node', "
                        f"format:'esm', outfile:{json.dumps(str(out))}}}))"
                    ),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(build.returncode, 0, build.stderr)

            result = subprocess.run(
                ["node", str(out)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_filters_from_slice_payload_restores_saved_slice_fields(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node is not available")
        esbuild_check = subprocess.run(
            ["node", "-e", "import('esbuild').catch(() => process.exit(1))"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if esbuild_check.returncode != 0:
            self.skipTest("esbuild is not available")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            entry = tmp_path / "filters_from_slice_entry.ts"
            out = tmp_path / "filters_from_slice_entry.mjs"
            entry.write_text(
                textwrap.dedent(
                    f"""
                    import {{ filtersFromSlicePayload }} from {json.dumps(str(ROOT / "apps/web/src/workbench.ts"))};
                    import {{ DEFAULT_FILTERS }} from {json.dumps(str(ROOT / "apps/web/src/domain.ts"))};

                    const filters = filtersFromSlicePayload({{
                      entity_level: "topic",
                      entity_id_short: "T10260",
                      entity_display_name: "Software Engineering Research",
                      filter_mode: "primary_topic",
                      institution_id: "I1",
                      institution_display_name: "Test University",
                      country_code: "ru",
                      from_publication_date: "2021-01-01",
                      to_publication_date: "2026-12-31",
                      work_type: "article",
                      min_cited_by_count: 3,
                    }}, DEFAULT_FILTERS);

                    if (filters.subject_id !== "T10260" || filters.subject_name !== "Software Engineering Research") {{
                      throw new Error(`subject was not restored: ${{JSON.stringify(filters)}}`);
                    }}
                    if (filters.country_code !== "RU" || filters.institution_name !== "Test University" || filters.min_cited_by_count !== "3") {{
                      throw new Error(`scoped fields were not restored: ${{JSON.stringify(filters)}}`);
                    }}
                    """
                ),
                encoding="utf-8",
            )

            build = subprocess.run(
                [
                    "node",
                    "-e",
                    (
                        "import('esbuild').then(({build}) => "
                        f"build({{entryPoints:[{json.dumps(str(entry))}], bundle:true, platform:'node', "
                        f"format:'esm', outfile:{json.dumps(str(out))}}}))"
                    ),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(build.returncode, 0, build.stderr)

            result = subprocess.run(
                ["node", str(out)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_local_data_missing_scope_state_distinguishes_empty_active_context(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node is not available")
        esbuild_check = subprocess.run(
            ["node", "-e", "import('esbuild').catch(() => process.exit(1))"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if esbuild_check.returncode != 0:
            self.skipTest("esbuild is not available")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            entry = tmp_path / "local_data_missing_scope_entry.ts"
            out = tmp_path / "local_data_missing_scope_entry.mjs"
            entry.write_text(
                textwrap.dedent(
                    f"""
                    import {{ localDataMissingScopeState }} from {json.dumps(str(ROOT / "apps/web/src/workbench.ts"))};

                    const scoped = localDataMissingScopeState({{ runId: "run_a" }});
                    if (scoped.missing !== false || scoped.detail !== "") {{
                      throw new Error(`expected explicit run to be ready, got ${{JSON.stringify(scoped)}}`);
                    }}

                    const noContext = localDataMissingScopeState({{}});
                    if (noContext.missing !== true || !noContext.detail.includes("нужен активный расчет")) {{
                      throw new Error(`expected missing active context detail, got ${{JSON.stringify(noContext)}}`);
                    }}

                    const emptyActive = localDataMissingScopeState({{ activeContext: {{ source: "stale" }} }});
                if (emptyActive.missing !== true || !emptyActive.detail.includes("не содержит расчета или локального среза")) {{
                      throw new Error(`expected empty active context detail, got ${{JSON.stringify(emptyActive)}}`);
                    }}
                    """
                ),
                encoding="utf-8",
            )

            build = subprocess.run(
                [
                    "node",
                    "-e",
                    (
                        "import('esbuild').then(({build}) => "
                        f"build({{entryPoints:[{json.dumps(str(entry))}], bundle:true, platform:'node', "
                        f"format:'esm', outfile:{json.dumps(str(out))}}}))"
                    ),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(build.returncode, 0, build.stderr)

            result = subprocess.run(
                ["node", str(out)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
