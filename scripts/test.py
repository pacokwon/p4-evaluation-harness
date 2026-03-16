import os
import re
from pathlib import Path


def get_excluded_paths(
    excludes_dir: str, test_suite_dir: str, ignore_list: list[str] | None = None
):
    test_suite_path = Path(test_suite_dir).resolve()
    exclude_root = Path(excludes_dir).resolve()

    # Pre-index the flattened suite for performance
    suite_files = {f: str(test_suite_path / f) for f in os.listdir(test_suite_path)}

    excluded_full_paths = set()
    ignores = [str(Path(p)) for p in ignore_list] if ignore_list else []

    for root, _, files in os.walk(exclude_root):
        for file in files:
            if not file.endswith(".exclude"):
                continue

            rel_path = str(Path(root).relative_to(exclude_root) / file)
            if any(
                rel_path == ig or rel_path.startswith(str(Path(ig)) + os.sep)
                for ig in ignores
            ):
                continue

            with open(os.path.join(root, file), "r") as f:
                for line in f:
                    entry = line.strip()
                    if not entry:
                        continue

                    entry_path = Path(entry)
                    entry_parts = set(entry_path.parts)

                    # --- THE SMART GUARD ---
                    # Check if the line mentions a protected directory
                    if (
                        "p4_16_samples" in entry_parts
                        and "p4_16_errors" in test_suite_dir
                    ) or (
                        "p4_16_errors" in entry_parts
                        and "p4_16_errors" not in test_suite_dir
                    ):
                        continue

                    stem = entry_path.stem
                    suffix = entry_path.suffix

                    # --- Logic: p4testgen STF renaming ---
                    if "testdata/p4testgen" in entry and suffix == ".stf":
                        match = re.match(r"(.+)_(\d+)$", stem)
                        if match:
                            target_p4 = f"{match.group(1)}__{match.group(2)}.p4"
                            if target_p4 in suite_files:
                                excluded_full_paths.add(suite_files[target_p4])
                        elif f"{stem}.stf" in suite_files:
                            excluded_full_paths.add(suite_files[f"{stem}.stf"])

                    # --- Logic: P4 Family Expansion ---
                    elif suffix == ".p4":
                        if f"{stem}.p4" in suite_files:
                            excluded_full_paths.add(suite_files[f"{stem}.p4"])

                        family_pattern = re.compile(rf"^{re.escape(stem)}__\d+\.p4$")
                        for filename in suite_files:
                            if family_pattern.match(filename):
                                excluded_full_paths.add(suite_files[filename])

                    # --- Logic: Direct match for other files ---
                    else:
                        full_name = f"{stem}{suffix}"
                        if full_name in suite_files:
                            excluded_full_paths.add(suite_files[full_name])

    return list(excluded_full_paths)
