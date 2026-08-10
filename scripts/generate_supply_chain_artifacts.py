from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from uuid import uuid4

from packaging.requirements import Requirement
from packaging.utils import (
    InvalidSdistFilename,
    InvalidWheelFilename,
    canonicalize_name,
    parse_sdist_filename,
    parse_wheel_filename,
)

ROOT = Path(__file__).resolve().parents[1]


def artifact_identity(path: Path) -> tuple[str, str]:
    if path.name.endswith(".whl"):
        name, version, _build, _tags = parse_wheel_filename(path.name)
    else:
        name, version = parse_sdist_filename(path.name)
    return canonicalize_name(name), str(version)


def write_hashed_lock(wheelhouse: Path, output: Path) -> None:
    artifacts: dict[tuple[str, str], list[str]] = defaultdict(list)
    for path in sorted(wheelhouse.iterdir()):
        if not path.is_file():
            continue
        try:
            identity = artifact_identity(path)
        except (InvalidWheelFilename, InvalidSdistFilename, ValueError):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        artifacts[identity].append(digest)
    if not artifacts:
        raise RuntimeError("No Python distribution artifacts found in the wheelhouse.")

    lines = [
        "# Generated from resolved distribution artifacts.",
        "# Install with: python -m pip install --require-hashes -r requirements.lock",
    ]
    for (name, version), hashes in sorted(artifacts.items()):
        hash_args = " ".join(f"--hash=sha256:{digest}" for digest in sorted(set(hashes)))
        lines.append(f"{name}=={version} {hash_args}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def direct_requirements(requirements_path: Path | None = None) -> set[str]:
    requirements_path = requirements_path or (ROOT / "requirements.txt")
    names: set[str] = set()
    for line in requirements_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.add(canonicalize_name(Requirement(line).name))
    return names


def resolved_dependency_name(raw_requirement: str) -> str | None:
    try:
        requirement = Requirement(raw_requirement)
    except ValueError:
        return None
    if requirement.marker is not None and not requirement.marker.evaluate():
        return None
    return canonicalize_name(requirement.name)


def write_sbom(output: Path, requirements_path: Path | None = None) -> None:
    direct_names = direct_requirements(requirements_path)
    distributions = {
        canonicalize_name(dist.metadata["Name"]): dist
        for dist in metadata.distributions()
        if dist.metadata.get("Name")
    }
    required_names = set(direct_names)
    pending = list(direct_names)
    while pending:
        name = pending.pop()
        distribution = distributions.get(name)
        if distribution is None:
            continue
        for raw_requirement in distribution.requires or []:
            dependency_name = resolved_dependency_name(raw_requirement)
            if dependency_name is None:
                continue
            if dependency_name in distributions and dependency_name not in required_names:
                required_names.add(dependency_name)
                pending.append(dependency_name)

    components: list[dict[str, object]] = []
    dependencies: list[dict[str, object]] = []
    for name in sorted(required_names):
        dist = distributions.get(name)
        if dist is None:
            continue
        version = dist.version
        reference = f"pkg:pypi/{name}@{version}"
        components.append(
            {
                "type": "library",
                "bom-ref": reference,
                "name": name,
                "version": version,
                "purl": reference,
                "scope": "required",
                "properties": [
                    {
                        "name": "touchvn:dependency-scope",
                        "value": "direct" if name in direct_names else "transitive",
                    }
                ],
            }
        )
        dependency_refs: list[str] = []
        for raw_requirement in dist.requires or []:
            dependency_name = resolved_dependency_name(raw_requirement)
            if dependency_name is None:
                continue
            dependency_dist = distributions.get(dependency_name)
            if dependency_dist is not None and dependency_name in required_names:
                dependency_refs.append(f"pkg:pypi/{dependency_name}@{dependency_dist.version}")
        dependencies.append({"ref": reference, "dependsOn": sorted(set(dependency_refs))})

    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "component": {
                "type": "application",
                "name": "touch-vietnam",
                "version": "1.1.0",
            },
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "Touch VN supply-chain generator",
                        "version": "1.0",
                    }
                ]
            },
        },
        "components": components,
        "dependencies": dependencies,
    }
    output.write_text(
        json.dumps(sbom, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def verify_lock(lock_path: Path, requirements_path: Path | None = None) -> None:
    lock_lines = [
        line.strip()
        for line in lock_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if not lock_lines or any(
        "==" not in line or "--hash=sha256:" not in line for line in lock_lines
    ):
        raise RuntimeError("requirements.lock must pin and hash every resolved dependency.")
    locked_names = {
        canonicalize_name(re.split(r"==", line, maxsplit=1)[0].strip()) for line in lock_lines
    }
    missing = sorted(direct_requirements(requirements_path) - locked_names)
    if missing:
        raise RuntimeError(f"requirements.lock is missing direct dependencies: {missing}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument(
        "--lock-output",
        type=Path,
        default=ROOT / "requirements.lock",
    )
    parser.add_argument(
        "--sbom-output",
        type=Path,
        default=ROOT / "sbom.cdx.json",
    )
    parser.add_argument(
        "--requirements",
        type=Path,
        default=ROOT / "requirements.txt",
    )
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    try:
        if args.wheelhouse:
            write_hashed_lock(args.wheelhouse, args.lock_output)
        if args.verify:
            verify_lock(args.lock_output, args.requirements)
            if not args.sbom_output.exists():
                raise RuntimeError(f"SBOM does not exist: {args.sbom_output}")
            json.loads(args.sbom_output.read_text(encoding="utf-8"))
        else:
            write_sbom(args.sbom_output, args.requirements)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Supply-chain artifacts: FAIL - {exc}")
        return 1
    print(f"SBOM={args.sbom_output}")
    if args.lock_output.exists():
        print(f"LOCK={args.lock_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
