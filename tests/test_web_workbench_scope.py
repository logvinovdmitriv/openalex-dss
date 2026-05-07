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
                    if (noContext.missing !== true || !noContext.detail.includes("нужен активный run_id")) {{
                      throw new Error(`expected missing active context detail, got ${{JSON.stringify(noContext)}}`);
                    }}

                    const emptyActive = localDataMissingScopeState({{ activeContext: {{ source: "legacy" }} }});
                    if (emptyActive.missing !== true || !emptyActive.detail.includes("не содержит run_id")) {{
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
