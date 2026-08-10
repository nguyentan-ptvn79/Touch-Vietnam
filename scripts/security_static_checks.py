from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = (ROOT / "app", ROOT / "scripts")
IGNORED_FILES = {Path(__file__).resolve()}
DANGEROUS_BUILTINS = {"eval", "exec"}
DANGEROUS_CALLS = {
    "pickle.load",
    "pickle.loads",
    "marshal.load",
    "marshal.loads",
    "yaml.load",
}


def call_name(node: ast.Call) -> str:
    parts: list[str] = []
    current = node.func
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def scan_python(path: Path) -> list[str]:
    findings: list[str] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        return [f"{path.relative_to(ROOT)}: parse failure: {exc}"]

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = call_name(node)
        short_name = name.rsplit(".", 1)[-1]
        if name in DANGEROUS_CALLS or short_name in DANGEROUS_BUILTINS:
            findings.append(f"{path.relative_to(ROOT)}:{node.lineno}: dangerous call {name}")
        if name.startswith("subprocess."):
            shell_keyword = next(
                (keyword for keyword in node.keywords if keyword.arg == "shell"),
                None,
            )
            if (
                shell_keyword
                and isinstance(shell_keyword.value, ast.Constant)
                and shell_keyword.value.value
            ):
                findings.append(f"{path.relative_to(ROOT)}:{node.lineno}: subprocess shell=True")
        if (
            short_name in {"execute", "executemany"}
            and node.args
            and isinstance(node.args[0], (ast.JoinedStr, ast.BinOp))
        ):
            findings.append(f"{path.relative_to(ROOT)}:{node.lineno}: dynamic SQL expression")
        if short_name in {"render_template_string", "Markup"}:
            findings.append(
                f"{path.relative_to(ROOT)}:{node.lineno}: unsafe HTML construction via {short_name}"
            )
    return findings


def scan_templates() -> list[str]:
    findings: list[str] = []
    for path in (ROOT / "app" / "web" / "templates").rglob("*.html"):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\|\s*safe\b", source):
            line = source.count("\n", 0, match.start()) + 1
            findings.append(
                f"{path.relative_to(ROOT)}:{line}: Jinja safe filter bypasses autoescape"
            )
    return findings


def scan_release_secrets() -> list[str]:
    findings: list[str] = []
    candidates = [
        ROOT / "README.md",
        ROOT / "package_release.ps1",
        ROOT / "docs" / "requirements-audit.md",
        ROOT / "docs" / "bang-nghiem-thu-khoa-luan.md",
    ]
    credential_pattern = re.compile(
        r"admin@touchvn\.com\s*(?:/|,|;|\||-).{0,30}(?:123456|password)",
        re.IGNORECASE,
    )
    for path in candidates:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        for match in credential_pattern.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            findings.append(f"{path.relative_to(ROOT)}:{line}: published demo credential")
    return findings


def main() -> int:
    findings: list[str] = []
    for scan_dir in SCAN_DIRS:
        for path in scan_dir.rglob("*.py"):
            if path.resolve() not in IGNORED_FILES:
                findings.extend(scan_python(path))
    findings.extend(scan_templates())
    findings.extend(scan_release_secrets())

    if findings:
        print("Static security checks: FAIL")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("Static security checks: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
