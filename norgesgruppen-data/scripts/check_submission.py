from __future__ import annotations

import argparse
import ast
import io
import zipfile
from pathlib import Path, PurePosixPath

ALLOWED_EXTENSIONS = {".py", ".json", ".yaml", ".yml", ".cfg", ".pt", ".pth", ".onnx", ".safetensors", ".npy"}
WEIGHT_EXTENSIONS = {".pt", ".pth", ".onnx", ".safetensors", ".npy"}
MAX_BYTES = 420 * 1024 * 1024
BANNED_IMPORTS = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "ctypes",
    "builtins",
    "importlib",
    "pickle",
    "marshal",
    "shelve",
    "shutil",
    "yaml",
    "requests",
    "urllib",
    "http",
    "multiprocessing",
    "threading",
    "signal",
    "gc",
    "code",
    "codeop",
    "pty",
}
BANNED_CALLS = {"eval", "exec", "compile", "__import__"}
DANGEROUS_GETATTR_NAMES = {"system", "popen", "remove", "unlink", "rmtree"}
EXECUTABLE_SIGNATURES = {
    b"\x7fELF": "ELF binary",
    b"MZ": "PE binary",
    b"\xcf\xfa\xed\xfe": "Mach-O binary",
    b"\xfe\xed\xfa\xcf": "Mach-O binary",
}


class SubmissionEntry:
    def __init__(self, name: str, size: int, is_symlink: bool, read_bytes):
        self.name = name
        self.size = size
        self.is_symlink = is_symlink
        self._read_bytes = read_bytes

    @property
    def suffix(self) -> str:
        return PurePosixPath(self.name).suffix

    def read_prefix(self, size: int = 512) -> bytes:
        return self._read_bytes(size)

    def read_text(self) -> str:
        return self._read_bytes(self.size).decode("utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a NorgesGruppen submission directory or zip.")
    parser.add_argument("submission_path", type=Path, help="Directory that will become the zip root, or a .zip file.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = args.submission_path.resolve()
    if not path.exists():
        raise SystemExit(f"Missing path: {path}")

    if path.is_dir():
        entries = load_entries_from_directory(path)
        source_label = str(path)
    elif path.suffix == ".zip":
        entries = load_entries_from_zip(path)
        source_label = str(path)
    else:
        raise SystemExit("submission_path must be a directory or a .zip file")

    errors = validate_entries(entries)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)

    python_files = [entry for entry in entries if entry.suffix == ".py"]
    weights = [entry for entry in entries if entry.suffix in WEIGHT_EXTENSIONS]
    total_size = sum(entry.size for entry in entries)
    print(f"OK: {source_label}")
    print(
        "files="
        f"{len(entries)} python_files={len(python_files)} weight_files={len(weights)} total_bytes={total_size}"
    )


def load_entries_from_directory(root: Path) -> list[SubmissionEntry]:
    entries = []
    for path in sorted(root.rglob("*")):
        relative_name = path.relative_to(root).as_posix()
        if should_ignore_local_artifact(relative_name):
            continue
        if path.is_dir():
            if path.is_symlink():
                entries.append(
                    SubmissionEntry(
                        name=relative_name,
                        size=0,
                        is_symlink=True,
                        read_bytes=lambda _: b"",
                    )
                )
            continue
        is_symlink = path.is_symlink()
        size = path.lstat().st_size if is_symlink else path.stat().st_size
        entries.append(
            SubmissionEntry(
                name=relative_name,
                size=size,
                is_symlink=is_symlink,
                read_bytes=lambda limit, path=path: path.read_bytes()[:limit],
            )
        )
    return entries


def should_ignore_local_artifact(relative_name: str) -> bool:
    parts = PurePosixPath(relative_name).parts
    return "__pycache__" in parts


def load_entries_from_zip(zip_path: Path) -> list[SubmissionEntry]:
    entries = []
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            name = info.filename.rstrip("/")
            if not name:
                continue
            if info.is_dir():
                continue
            is_symlink = is_zip_symlink(info)
            entries.append(
                SubmissionEntry(
                    name=name,
                    size=info.file_size,
                    is_symlink=is_symlink,
                    read_bytes=lambda limit, zip_path=zip_path, name=name: read_zip_bytes(zip_path, name, limit),
                )
            )
    return entries


def is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == 0o120000


def read_zip_bytes(zip_path: Path, member_name: str, limit: int) -> bytes:
    with zipfile.ZipFile(zip_path) as archive:
        with archive.open(member_name, "r") as file_obj:
            return file_obj.read(limit)


def validate_entries(entries: list[SubmissionEntry]) -> list[str]:
    errors: list[str] = []
    file_names = [entry.name for entry in entries]

    if "run.py" not in file_names:
        errors.append("run.py must exist at the zip root.")

    if len(entries) > 1000:
        errors.append(f"Too many files: {len(entries)} > 1000")

    python_files = [entry for entry in entries if entry.suffix == ".py"]
    if len(python_files) > 10:
        errors.append(f"Too many Python files: {len(python_files)} > 10")

    weights = [entry for entry in entries if entry.suffix in WEIGHT_EXTENSIONS]
    if len(weights) > 3:
        errors.append(f"Too many weight files: {len(weights)} > 3")

    total_weight_size = sum(entry.size for entry in weights)
    if total_weight_size > MAX_BYTES:
        errors.append(f"Weight files total {total_weight_size} bytes, above 420 MB.")

    total_size = sum(entry.size for entry in entries)
    if total_size > MAX_BYTES:
        errors.append(f"Submission totals {total_size} bytes, above 420 MB.")

    for entry in entries:
        validate_entry_path(entry, errors)
        if entry.is_symlink:
            errors.append(f"Symlinks are not allowed: {entry.name}")
            continue
        if entry.suffix not in ALLOWED_EXTENSIONS:
            errors.append(f"Disallowed file type: {entry.name}")
            continue
        validate_binary_signature(entry, errors)
        if entry.suffix == ".py":
            errors.extend(validate_python_source(entry))

    return errors


def validate_entry_path(entry: SubmissionEntry, errors: list[str]) -> None:
    pure_path = PurePosixPath(entry.name)
    if pure_path.is_absolute():
        errors.append(f"Absolute paths are not allowed: {entry.name}")
    if any(part == ".." for part in pure_path.parts):
        errors.append(f"Path traversal is not allowed: {entry.name}")
    if any(part == "__MACOSX" for part in pure_path.parts):
        errors.append(f"Disallowed macOS metadata path: {entry.name}")


def validate_binary_signature(entry: SubmissionEntry, errors: list[str]) -> None:
    header = entry.read_prefix(8)
    for signature, description in EXECUTABLE_SIGNATURES.items():
        if header.startswith(signature):
            errors.append(f"{description} is not allowed: {entry.name}")


def validate_python_source(entry: SubmissionEntry) -> list[str]:
    errors: list[str] = []
    try:
        source = entry.read_text()
        tree = ast.parse(source, filename=entry.name)
    except UnicodeDecodeError:
        return [f"Python file is not valid UTF-8: {entry.name}"]
    except SyntaxError as exc:
        return [f"Python file has invalid syntax: {entry.name}:{exc.lineno} {exc.msg}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_name = alias.name.split(".")[0]
                if root_name in BANNED_IMPORTS:
                    errors.append(f"Banned import '{root_name}' in {entry.name}:{node.lineno}")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_name = node.module.split(".")[0]
                if root_name in BANNED_IMPORTS:
                    errors.append(f"Banned import '{root_name}' in {entry.name}:{node.lineno}")
        elif isinstance(node, ast.Call):
            call_name = get_call_name(node.func)
            if call_name in BANNED_CALLS:
                errors.append(f"Banned call '{call_name}' in {entry.name}:{node.lineno}")
            if call_name == "getattr" and len(node.args) >= 2:
                second_arg = node.args[1]
                if isinstance(second_arg, ast.Constant) and second_arg.value in DANGEROUS_GETATTR_NAMES:
                    errors.append(
                        f"Dangerous getattr target '{second_arg.value}' in {entry.name}:{node.lineno}"
                    )
    return errors


def get_call_name(node) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


if __name__ == "__main__":
    main()
