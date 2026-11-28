"""The server image ships a compiled MockUSDC artifact and no Foundry (FND-07)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from detent import devchain


def _files(tmp_path: Path, *, artifact_newer: bool) -> tuple[Path, Path]:
    source = tmp_path / "MockUSDC.sol"
    artifact = tmp_path / "MockUSDC.json"
    source.write_text("// source")
    artifact.write_text("{}")
    older, newer = 1_000_000, 2_000_000
    os.utime(source, (older, older) if artifact_newer else (newer, newer))
    os.utime(artifact, (newer, newer) if artifact_newer else (older, older))
    return source, artifact


def test_existing_artifact_is_used_without_forge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, artifact = _files(tmp_path, artifact_newer=False)  # e.g. COPY gave the source a later mtime
    monkeypatch.setattr(devchain, "SOURCE", source)
    monkeypatch.setattr(devchain, "ARTIFACT", artifact)
    monkeypatch.setattr(devchain, "_have", lambda name: False)
    monkeypatch.setattr("subprocess.run", pytest.fail)
    devchain.build_contracts()  # no forge call, no error


def test_stale_artifact_is_rebuilt_when_forge_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, artifact = _files(tmp_path, artifact_newer=False)
    monkeypatch.setattr(devchain, "SOURCE", source)
    monkeypatch.setattr(devchain, "ARTIFACT", artifact)
    monkeypatch.setattr(devchain, "_have", lambda name: True)
    monkeypatch.setattr(devchain, "_bin", lambda name: "/bin/forge")
    calls: list[list[str]] = []
    monkeypatch.setattr("subprocess.run", lambda cmd, check: calls.append(cmd))
    devchain.build_contracts()
    assert calls and calls[0][:2] == ["/bin/forge", "build"]


def test_missing_artifact_without_forge_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(devchain, "SOURCE", tmp_path / "MockUSDC.sol")
    monkeypatch.setattr(devchain, "ARTIFACT", tmp_path / "missing.json")
    monkeypatch.setattr(devchain, "_bin", lambda name: (_ for _ in ()).throw(FileNotFoundError(name)))
    with pytest.raises(FileNotFoundError):
        devchain.build_contracts()
