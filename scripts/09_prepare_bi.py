#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))

from app.services.bi import prepare_warehouse  # noqa: E402


def main() -> None:
    print(json.dumps(prepare_warehouse(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
