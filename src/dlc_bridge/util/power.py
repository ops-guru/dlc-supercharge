"""FR-16 Kiro Powers registry writer.

Port of v1.1 ``register-kiro-power.ps1``. Performs the layer-2 install steps
that make a custom Power visible in Kiro's Powers panel:

1. Copies ``POWER.md``, ``mcp.json`` (if present), and ``steering/*`` from
   the bundle into ``~/.kiro/powers/installed/<name>/``.
2. Updates ``~/.kiro/powers/registries/user-added.json`` (replace-then-append
   semantics — the same power name never appears twice).
3. Updates ``~/.kiro/powers/installed.json`` similarly.

**Critical:** all JSON writes go through :func:`util.encoding.write_json_utf8_lf`
to guarantee no UTF-8 BOM. Kiro's JSON parser rejects BOM-prefixed input
(this is the bug v1.0.1 fixed).

The ``version`` argument is a v2 extension. v1.1 didn't track per-power
version in the registry; we record it under ``installedPowers[].version`` so
later cache-validation and upgrade flows can consult it. Back-compat: missing
``version`` on reads is fine.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from dlc_bridge.exceptions import ValidationError
from dlc_bridge.util.encoding import (
    read_text_utf8,
    write_json_utf8_lf,
)

__all__ = ["register_power"]


def _iso_now() -> str:
    """Return an ISO-8601 UTC timestamp for ``installedAt``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _powers_home(home: Path | None) -> Path:
    """Return the ``.kiro/powers`` directory under ``home`` (or ``~``)."""
    base = home if home is not None else Path.home()
    return Path(base) / ".kiro" / "powers"


def _read_json(path: Path) -> dict | None:
    """Read a JSON file, returning ``None`` on missing / malformed input.

    Tolerates a leading UTF-8 BOM so v1.0.0-era files (written with BOM) can
    be migrated forward without losing entries.
    """
    if not path.exists():
        return None
    try:
        import json
        return json.loads(read_text_utf8(path))
    except (ValueError, OSError):
        return None


def register_power(
    *,
    name: str,
    version: str,
    source_dir: Path,
    home: Path | None = None,
    dry_run: bool = False,
) -> dict:
    """Register a Power with Kiro's user-scoped registry.

    :param name: power slug (e.g. ``"dlc-supercharge"``).
    :param version: semver string (v2 extension; recorded under
        ``installedPowers[].version``).
    :param source_dir: bundle folder containing ``POWER.md`` (and optionally
        ``mcp.json``, ``steering/``).
    :param home: override ``~`` for tests; default :func:`Path.home`.
    :param dry_run: if ``True``, perform no filesystem mutations and return
        ``status: "dry-run"``.
    :returns: dict ``{status, name, version, paths}`` where ``status`` is one
        of ``registered`` (new), ``updated`` (existing), or ``dry-run``.
    :raises ValidationError: if ``source_dir`` is missing or has no ``POWER.md``.
    """
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        raise ValidationError(f"source_dir not a directory: {source_dir}")
    if not (source_dir / "POWER.md").is_file():
        raise ValidationError(
            f"source_dir missing POWER.md: {source_dir}"
        )

    powers_home = _powers_home(home)
    installed_dir = powers_home / "installed" / name
    registries_dir = powers_home / "registries"
    user_added_path = registries_dir / "user-added.json"
    installed_json_path = powers_home / "installed.json"

    paths_touched: list[Path] = []

    # Check whether this is an update before mutating anything.
    existing_installed = _read_json(installed_json_path) or {}
    existing_powers = existing_installed.get("installedPowers", [])
    is_update = any(p.get("name") == name for p in existing_powers if isinstance(p, dict))

    if dry_run:
        return {
            "status": "dry-run",
            "name": name,
            "version": version,
            "paths": [
                str(installed_dir),
                str(user_added_path),
                str(installed_json_path),
            ],
        }

    # 1. Copy bundle files into ~/.kiro/powers/installed/<name>/.
    installed_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_dir / "POWER.md", installed_dir / "POWER.md")
    paths_touched.append(installed_dir / "POWER.md")
    if (source_dir / "mcp.json").is_file():
        shutil.copy2(source_dir / "mcp.json", installed_dir / "mcp.json")
        paths_touched.append(installed_dir / "mcp.json")
    steering_src = source_dir / "steering"
    if steering_src.is_dir():
        steering_dst = installed_dir / "steering"
        if steering_dst.exists():
            shutil.rmtree(steering_dst)
        shutil.copytree(steering_src, steering_dst)
        paths_touched.append(steering_dst)

    # 2. Update user-added.json (replace-then-append).
    registries_dir.mkdir(parents=True, exist_ok=True)
    user_added = _read_json(user_added_path) or {"powers": []}
    powers_list = [
        p for p in user_added.get("powers", [])
        if isinstance(p, dict) and p.get("name") != name
    ]
    powers_list.append(
        {
            "name": name,
            "description": f"Custom power from {source_dir}",
            "source": {"type": "local", "path": str(source_dir)},
        }
    )
    user_added = {"powers": powers_list}
    write_json_utf8_lf(user_added_path, user_added)
    paths_touched.append(user_added_path)

    # 3. Update installed.json.
    installed = existing_installed or {
        "version": "1.0.0",
        "installedPowers": [],
        "dismissedAutoInstalls": [],
    }
    if "installedPowers" not in installed or not isinstance(installed["installedPowers"], list):
        installed["installedPowers"] = []
    if "dismissedAutoInstalls" not in installed:
        installed["dismissedAutoInstalls"] = []

    installed_powers = [
        p for p in installed["installedPowers"]
        if isinstance(p, dict) and p.get("name") != name
    ]
    installed_powers.append(
        {
            "name": name,
            "registryId": "user-added",
            "version": version,
            "installedAt": _iso_now(),
        }
    )
    installed["installedPowers"] = installed_powers
    write_json_utf8_lf(installed_json_path, installed)
    paths_touched.append(installed_json_path)

    return {
        "status": "updated" if is_update else "registered",
        "name": name,
        "version": version,
        "paths": [str(p) for p in paths_touched],
    }
