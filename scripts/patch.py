#!/usr/bin/env python3

import argparse
import re
import shutil
from pathlib import Path


# Syntactic dotted-name expression:
# ident(.ident)*
DOTTED_NAME_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\[[0-9]+(?::[0-9]+)?\])*(?:\.(?:\$[A-Za-z_]+\$|[A-Za-z_][A-Za-z0-9_]*(?:\[[0-9]+(?::[0-9]+)?\])*))*$"
)

# Match double-quoted strings
DOUBLE_QUOTED_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')

# Match action calls like foo.bar(...)
ACTION_CALL_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\(([^()]*)\)")


def is_valid_dotted_name(s: str) -> bool:
    return DOTTED_NAME_RE.fullmatch(s) is not None


def normalize_action_args(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        args = match.group(2)
        args = re.sub(r",\s+", ",", args)
        return f"{name}({args})"

    return ACTION_CALL_RE.sub(repl, text)


def patch_stf_text(text: str) -> str:
    def unquote_repl(match: re.Match[str]) -> str:
        inner = match.group(1)

        if "\\" in inner:
            return match.group(0)

        if is_valid_dotted_name(inner):
            return inner

        return match.group(0)

    # 1. Remove double quotes around syntactically valid dotted names
    text = DOUBLE_QUOTED_RE.sub(unquote_repl, text)

    # 2. Normalize ", " -> "," inside action argument lists
    text = normalize_action_args(text)

    return text


def make_output_dir(src_dir: Path) -> Path:
    return src_dir.parent / f"{src_dir.name}_patched"


def patch_files(directory: Path) -> None:
    for stf_path in directory.rglob("*.stf"):
        original = stf_path.read_text(encoding="utf-8")
        patched = patch_stf_text(original)
        stf_path.write_text(patched, encoding="utf-8")


def patch_directory(src_dir: Path, dst_dir: Path) -> None:
    if dst_dir.exists():
        raise FileExistsError(f"Destination already exists: {dst_dir}")

    shutil.copytree(src_dir, dst_dir)
    patch_files(dst_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Patch .stf files by unquoting syntactically valid dotted names and normalizing action arg spacing."
    )
    parser.add_argument("directory", help="Source directory")
    parser.add_argument(
        "--output",
        help="Output directory (default: <directory>_patched)",
        default=None,
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Patch files in place instead of copying",
    )

    args = parser.parse_args()

    src_dir = Path(args.directory).resolve()
    if not src_dir.is_dir():
        raise NotADirectoryError(f"Not a directory: {src_dir}")

    if args.in_place and args.output:
        raise ValueError("--output and --in-place cannot be used together")

    if args.in_place:
        patch_files(src_dir)
        print(f"Patched files in-place in: {src_dir}")
        return

    dst_dir = Path(args.output).resolve() if args.output else make_output_dir(src_dir)
    patch_directory(src_dir, dst_dir)

    print(f"Patched copy created at: {dst_dir}")


if __name__ == "__main__":
    main()
