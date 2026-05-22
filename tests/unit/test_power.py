"""Tests for :mod:`dlc_bridge.util.power` (FR-16 Powers registration)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dlc_bridge.exceptions import ValidationError
from dlc_bridge.util.power import register_power


_UTF8_BOM = b"\xef\xbb\xbf"


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    """A minimal Power bundle directory with POWER.md + mcp.json + steering/."""
    src = tmp_path / "bundle"
    src.mkdir()
    (src / "POWER.md").write_text("# My Power\n", encoding="utf-8")
    (src / "mcp.json").write_text('{"version": 1}\n', encoding="utf-8")
    (src / "steering").mkdir()
    (src / "steering" / "context.md").write_text("steering content\n", encoding="utf-8")
    return src


@pytest.fixture
def fake_home(tmp_path: Path) -> Path:
    """A per-test ``$HOME`` substitute."""
    home = tmp_path / "home"
    home.mkdir()
    return home


def _read_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


class TestRegisterPower:
    def test_fresh_install(self, bundle: Path, fake_home: Path) -> None:
        result = register_power(
            name="my-power",
            version="1.0.0",
            source_dir=bundle,
            home=fake_home,
        )
        assert result["status"] == "registered"
        assert result["name"] == "my-power"
        assert result["version"] == "1.0.0"

        # Bundle files copied.
        installed_dir = fake_home / ".kiro" / "powers" / "installed" / "my-power"
        assert (installed_dir / "POWER.md").is_file()
        assert (installed_dir / "mcp.json").is_file()
        assert (installed_dir / "steering" / "context.md").is_file()

        # Both registries populated.
        ua = _read_json(fake_home / ".kiro" / "powers" / "registries" / "user-added.json")
        assert any(p["name"] == "my-power" for p in ua["powers"])
        inst = _read_json(fake_home / ".kiro" / "powers" / "installed.json")
        assert any(p["name"] == "my-power" for p in inst["installedPowers"])

    def test_no_bom_in_json_writes(self, bundle: Path, fake_home: Path) -> None:
        register_power(
            name="my-power", version="1.0.0", source_dir=bundle, home=fake_home
        )
        for path in [
            fake_home / ".kiro" / "powers" / "installed.json",
            fake_home / ".kiro" / "powers" / "registries" / "user-added.json",
        ]:
            assert not path.read_bytes().startswith(_UTF8_BOM)

    def test_lf_only_in_json_writes(self, bundle: Path, fake_home: Path) -> None:
        register_power(
            name="my-power", version="1.0.0", source_dir=bundle, home=fake_home
        )
        for path in [
            fake_home / ".kiro" / "powers" / "installed.json",
            fake_home / ".kiro" / "powers" / "registries" / "user-added.json",
        ]:
            assert b"\r\n" not in path.read_bytes()

    def test_reinstall_same_version_marks_updated(
        self, bundle: Path, fake_home: Path
    ) -> None:
        register_power(
            name="my-power", version="1.0.0", source_dir=bundle, home=fake_home
        )
        result = register_power(
            name="my-power", version="1.0.0", source_dir=bundle, home=fake_home
        )
        assert result["status"] == "updated"
        # Still only one entry in each registry.
        inst = _read_json(fake_home / ".kiro" / "powers" / "installed.json")
        names = [p["name"] for p in inst["installedPowers"]]
        assert names.count("my-power") == 1

    def test_upgrade_bumps_version(self, bundle: Path, fake_home: Path) -> None:
        register_power(
            name="my-power", version="1.0.0", source_dir=bundle, home=fake_home
        )
        register_power(
            name="my-power", version="2.0.0", source_dir=bundle, home=fake_home
        )
        inst = _read_json(fake_home / ".kiro" / "powers" / "installed.json")
        my = next(p for p in inst["installedPowers"] if p["name"] == "my-power")
        assert my["version"] == "2.0.0"

    def test_dry_run_no_filesystem_changes(
        self, bundle: Path, fake_home: Path
    ) -> None:
        result = register_power(
            name="my-power",
            version="1.0.0",
            source_dir=bundle,
            home=fake_home,
            dry_run=True,
        )
        assert result["status"] == "dry-run"
        installed_dir = fake_home / ".kiro" / "powers" / "installed" / "my-power"
        assert not installed_dir.exists()
        assert not (fake_home / ".kiro" / "powers" / "installed.json").exists()

    def test_missing_power_md_raises(self, tmp_path: Path, fake_home: Path) -> None:
        empty_bundle = tmp_path / "empty"
        empty_bundle.mkdir()
        with pytest.raises(ValidationError, match="POWER.md"):
            register_power(
                name="x", version="1.0.0", source_dir=empty_bundle, home=fake_home
            )

    def test_missing_source_dir_raises(self, tmp_path: Path, fake_home: Path) -> None:
        with pytest.raises(ValidationError):
            register_power(
                name="x",
                version="1.0.0",
                source_dir=tmp_path / "nonexistent",
                home=fake_home,
            )

    def test_multiple_powers_coexist(
        self, bundle: Path, fake_home: Path, tmp_path: Path
    ) -> None:
        # Second bundle.
        b2 = tmp_path / "bundle2"
        b2.mkdir()
        (b2 / "POWER.md").write_text("# Power 2\n", encoding="utf-8")

        register_power(
            name="power-one", version="1.0.0", source_dir=bundle, home=fake_home
        )
        register_power(
            name="power-two", version="0.5.0", source_dir=b2, home=fake_home
        )
        inst = _read_json(fake_home / ".kiro" / "powers" / "installed.json")
        names = sorted(p["name"] for p in inst["installedPowers"])
        assert names == ["power-one", "power-two"]

    def test_existing_installed_json_with_unrelated_powers_preserved(
        self, bundle: Path, fake_home: Path
    ) -> None:
        # Seed a pre-existing installed.json with another power.
        powers_dir = fake_home / ".kiro" / "powers"
        powers_dir.mkdir(parents=True)
        (powers_dir / "installed.json").write_text(
            json.dumps(
                {
                    "version": "1.0.0",
                    "installedPowers": [
                        {"name": "other-power", "registryId": "user-added"}
                    ],
                    "dismissedAutoInstalls": [],
                }
            ),
            encoding="utf-8",
        )
        register_power(
            name="my-power", version="1.0.0", source_dir=bundle, home=fake_home
        )
        inst = _read_json(powers_dir / "installed.json")
        names = sorted(p["name"] for p in inst["installedPowers"])
        assert "other-power" in names
        assert "my-power" in names

    def test_steering_directory_overwrite_on_reinstall(
        self, bundle: Path, fake_home: Path
    ) -> None:
        register_power(
            name="my-power", version="1.0.0", source_dir=bundle, home=fake_home
        )
        # Modify source, reinstall: dst should reflect new content.
        (bundle / "steering" / "context.md").write_text(
            "updated content\n", encoding="utf-8"
        )
        register_power(
            name="my-power", version="1.0.1", source_dir=bundle, home=fake_home
        )
        dst = (
            fake_home / ".kiro" / "powers" / "installed" / "my-power"
            / "steering" / "context.md"
        )
        assert "updated content" in dst.read_text(encoding="utf-8")
