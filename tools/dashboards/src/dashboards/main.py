"""Dashboard generator orchestrator.

Walks every registered dashboard module, calls its `build() -> dict`, and
writes the JSON to the module's `OUTPUT_PATH` (relative to the repo root).

CLI:
  uv run dashboards build           # regenerate every dashboard's JSON
  uv run dashboards check           # build to a tmpdir; fail if diff vs committed

Add a new dashboard:
  1. Create `<area>/<name>.py` exposing `build() -> dict` and
     `OUTPUT_PATH: str` (relative to repo root).
  2. Import it in `_DASHBOARDS` below.
  3. Run `uv run dashboards build` and commit the regenerated JSON.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import tempfile
from pathlib import Path
from types import ModuleType

# Registry of every generated dashboard. Import-by-string so Python's
# import-time errors don't blow up unrelated `--help`.
_DASHBOARD_MODULES: tuple[str, ...] = (
    "dashboards.envoy_ai_gateway.per_user",
    "dashboards.envoy_ai_gateway.cost_by_model",
    "dashboards.envoy_ai_gateway.actor_consumption",
    "dashboards.envoy_ai_gateway.user_tokens_cost",
    "dashboards.envoy_ai_gateway.scoreboard",
)


def _load_modules() -> list[ModuleType]:
    mods: list[ModuleType] = []
    for name in _DASHBOARD_MODULES:
        mods.append(importlib.import_module(name))
    return mods


def _validate_module(mod: ModuleType) -> None:
    for attr in ("build", "OUTPUT_PATH"):
        if not hasattr(mod, attr):
            raise RuntimeError(f"{mod.__name__}: missing required attr `{attr}`")
    if not callable(mod.build):  # type: ignore[attr-defined]
        raise RuntimeError(f"{mod.__name__}: `build` must be callable")
    if not isinstance(mod.OUTPUT_PATH, str):  # type: ignore[attr-defined]
        raise RuntimeError(f"{mod.__name__}: `OUTPUT_PATH` must be a str")


def _repo_root() -> Path:
    """tools/dashboards/src/dashboards/main.py → repo root is four levels up."""
    return Path(__file__).resolve().parents[4]


def _emit(mod: ModuleType, target_dir: Path) -> Path:
    dashboard = mod.build()  # type: ignore[attr-defined]
    out_path = target_dir / mod.OUTPUT_PATH  # type: ignore[attr-defined]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(dashboard, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out_path


def cmd_build() -> int:
    root = _repo_root()
    mods = _load_modules()
    for mod in mods:
        _validate_module(mod)
        out = _emit(mod, root)
        rel = out.relative_to(root)
        print(f"wrote {rel}", file=sys.stderr)
    return 0


def cmd_check() -> int:
    """Render every dashboard to a tmpdir; diff against the committed file.

    Exits 0 if every output matches; 1 if any differs (and prints the
    offending paths to stderr). Used as a CI guard so that hand-edits to
    generated JSON are caught.
    """
    root = _repo_root()
    mods = _load_modules()
    drift: list[str] = []
    with tempfile.TemporaryDirectory(prefix="dashboards-check-") as td:
        td_path = Path(td)
        for mod in mods:
            _validate_module(mod)
            tmp_out = _emit(mod, td_path)
            committed = root / mod.OUTPUT_PATH  # type: ignore[attr-defined]
            if not committed.exists():
                drift.append(f"MISSING {mod.OUTPUT_PATH}")  # type: ignore[attr-defined]
                continue
            if tmp_out.read_bytes() != committed.read_bytes():
                drift.append(mod.OUTPUT_PATH)  # type: ignore[attr-defined]
    if drift:
        print("dashboard drift:", file=sys.stderr)
        for d in drift:
            print(f"  {d}", file=sys.stderr)
        print(
            "\nrun `uv run dashboards build` and commit the regenerated files.",
            file=sys.stderr,
        )
        return 1
    print("ok — every dashboard matches its generator", file=sys.stderr)
    return 0


def cli() -> int:
    parser = argparse.ArgumentParser(prog="dashboards")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="regenerate every dashboard's JSON")
    sub.add_parser("check", help="build to a tmpdir; fail if any committed file differs")
    args = parser.parse_args()
    if args.cmd == "build":
        return cmd_build()
    if args.cmd == "check":
        return cmd_check()
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(cli())
