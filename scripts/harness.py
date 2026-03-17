from dataclasses import dataclass, field
from enum import Enum
from patch import patch_directory
from pathlib import Path
import datetime
import glob
import json
import os
import re
import shutil
import subprocess


class TestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


class Arch(Enum):
    V1MODEL = "V1MODEL"
    EBPF = "EBPF"


class StaticTestType(Enum):
    POS = "POS"
    NEG = "NEG"


StaticTestRecord = list[tuple[str, TestResult]]
DynamicTestRecord = list[tuple[str, str, TestResult]]


def get_time():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def dump_json(data, dir: str, label=""):
    filename = label + get_time() + ".json"
    filepath = str(Path(dir).resolve() / filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


@dataclass
class TestSuite:
    # absolute path to p4 file, absolute path to stf file (only populated in dynamic)
    pairs: set[tuple[str, str]] = field(default_factory=set)
    # set of p4 programs
    programs: set[str] = field(default_factory=set)
    # basename of excluded file
    excluded: set[str] = field(default_factory=set)


def get_p4_stf_pairs(directory_path: str) -> set[tuple[str, str]]:
    """
    Scans a directory for .p4 and .stf file pairs with matching stems.
    Returns a set of tuples: (abs_path_to_p4, abs_path_to_stf).
    """
    base_path = Path(directory_path).resolve()
    pairs = set()

    # Get a set of all .stf filenames for O(1) lookups
    # Using stem as the key: { 'foo': 'abs/path/to/foo.stf' }
    stf_files = {f.stem: str(f) for f in base_path.iterdir() if f.suffix == ".stf"}

    # Iterate through .p4 files and look for matches
    for p4_file in base_path.iterdir():
        if p4_file.suffix == ".p4":
            stem = p4_file.stem
            if stem in stf_files:
                pairs.add((str(p4_file), stf_files[stem]))

    return pairs


def read_test_suite(
    test_suite_dir: str,
    excludes_dir: str,
    ignore_list: list[str] | None = None,
    additional_list: list[str] | None = None,
) -> TestSuite:
    test_suite_path = Path(test_suite_dir).resolve()
    exclude_root = Path(excludes_dir).resolve()

    suite_files = {f: str(test_suite_path / f) for f in os.listdir(test_suite_path)}

    excluded_full_paths = set()
    ignores = [str(Path(p)) for p in ignore_list] if ignore_list else []

    # --- collect exclude files ---
    exclude_files = []

    for root, _, files in os.walk(exclude_root):
        for file in files:
            if file.endswith(".exclude"):
                exclude_files.append(Path(root) / file)

    if additional_list:
        exclude_files.extend(Path(p) for p in additional_list)

    # --- process exclude files ---
    for exclude_file in exclude_files:
        rel_path = (
            str(exclude_file.relative_to(exclude_root))
            if exclude_file.is_relative_to(exclude_root)
            else str(exclude_file)
        )

        if any(
            rel_path == ig or rel_path.startswith(str(Path(ig)) + os.sep)
            for ig in ignores
        ):
            continue

        with open(exclude_file, "r") as f:
            for line in f:
                entry = line.strip()
                if not entry:
                    continue

                entry_path = Path(entry)
                entry_parts = set(entry_path.parts)

                # --- THE SMART GUARD ---
                if (
                    "p4_16_samples" in entry_parts and "p4_16_errors" in test_suite_dir
                ) or (
                    "p4_16_errors" in entry_parts
                    and "p4_16_errors" not in test_suite_dir
                ):
                    continue

                stem = entry_path.stem
                suffix = entry_path.suffix

                if "testdata/p4testgen" in entry and suffix == ".stf":
                    match = re.match(r"(.+)_(\d+)$", stem)
                    if match:
                        target_p4 = f"{match.group(1)}__{match.group(2)}.p4"
                        if target_p4 in suite_files:
                            excluded_full_paths.add(suite_files[target_p4])
                    elif f"{stem}.stf" in suite_files:
                        excluded_full_paths.add(suite_files[f"{stem}.stf"])

                elif suffix == ".p4":
                    if f"{stem}.p4" in suite_files:
                        excluded_full_paths.add(suite_files[f"{stem}.p4"])

                    family_pattern = re.compile(rf"^{re.escape(stem)}__\d+\.p4$")
                    for filename in suite_files:
                        if family_pattern.match(filename):
                            excluded_full_paths.add(suite_files[filename])

                else:
                    full_name = f"{stem}{suffix}"
                    if full_name in suite_files:
                        excluded_full_paths.add(suite_files[full_name])

    excluded = {Path(path).name for path in excluded_full_paths}

    pairs = get_p4_stf_pairs(test_suite_dir)

    programs = set(suite_files.values())

    return TestSuite(programs=programs, pairs=pairs, excluded=excluded)


def is_exclude_program(excludes: set[str], program: str) -> bool:
    return Path(program).name in excludes


def is_exclude_pair(excludes: set[str], pair: tuple[str, str]) -> bool:
    p4_path, stf_path = pair

    return (Path(p4_path).name in excludes) or (Path(stf_path).name in excludes)


############################### STATIC ###############################


def run_p4spectec_static(
    test_suite: TestSuite, typ: StaticTestType
) -> StaticTestRecord:
    excluded = test_suite.excluded

    results: StaticTestRecord = []

    project_root = "/p4-spectec"

    for p4_path in test_suite.programs:
        if is_exclude_program(excluded, p4_path):
            results.append((p4_path, TestResult.SKIP))
            print(f"[SKIP] {p4_path}")
            continue

        watsup_files = sorted(glob.glob("/p4-spectec/spec-concrete/*/*.watsup"))
        command = (
            [
                "./p4spectec",
                "run",
            ]
            + watsup_files
            + ["-i", "p4c/p4include", "-rel", "Program_inst", "-sl", "-p", p4_path]
        )

        result = subprocess.run(
            command,
            cwd=project_root,
            stdout=subprocess.DEVNULL,
        )

        # 42 on success, 6 on failure
        if typ == StaticTestType.POS:
            if result.returncode == 42:
                results.append((p4_path, TestResult.PASS))
                print(f"[PASS] {p4_path}")
            else:
                results.append((p4_path, TestResult.FAIL))
                print(f"[FAIL] {p4_path}")
        else:
            if result.returncode == 6:
                results.append((p4_path, TestResult.PASS))
                print(f"[PASS] {p4_path}")
            else:
                results.append((p4_path, TestResult.FAIL))
                print(f"[FAIL] {p4_path}")

    print(len(results))

    dump_json(results, project_root, f"typecheck-{typ.value}-")

    return results


def run_petr4_static(test_suite: TestSuite, typ: StaticTestType) -> StaticTestRecord:
    excluded = test_suite.excluded

    results: StaticTestRecord = []

    project_root = "/petr4"

    for p4_path in test_suite.programs:
        if is_exclude_program(excluded, p4_path):
            results.append((p4_path, TestResult.SKIP))
            print("[SKIP]")
            continue

        command = ["./_opam/bin/petr4", "typecheck", "-I", "/p4include", p4_path]

        result = subprocess.run(
            command,
            cwd=project_root,
            stdout=subprocess.DEVNULL,
        )

        # 42 on success, 6 on failure
        if typ == StaticTestType.POS:
            if result.returncode == 42:
                results.append((p4_path, TestResult.PASS))
                print(f"[PASS] {p4_path}")
            else:
                results.append((p4_path, TestResult.FAIL))
                print(f"[FAIL] {p4_path}")
        else:
            if result.returncode == 6:
                results.append((p4_path, TestResult.PASS))
                print(f"[PASS] {p4_path}")
            else:
                results.append((p4_path, TestResult.FAIL))
                print(f"[FAIL] {p4_path}")

    print(len(results))

    dump_json(results, project_root, f"typecheck-{typ.value}-")

    return results


############################### DYNAMIC ###############################


def hol4p4_collect_test_results(dir: str, test_suite: TestSuite) -> DynamicTestRecord:
    target_dir = Path(dir)
    obj_dir = target_dir / ".hol" / "objs"
    results = []

    for p4_file, stf_file in test_suite.pairs:
        print(f"{p4_file}\t{stf_file}")

        if is_exclude_pair(test_suite.excluded, (p4_file, stf_file)):
            results.append((p4_file, stf_file, TestResult.SKIP))
            continue

        p4_file_pathobj = Path(p4_file)
        base_name = p4_file_pathobj.stem

        theory_name = base_name.replace("-", "_")
        theory_file = obj_dir / f"{theory_name}Theory.uo"

        if theory_file.is_file():
            results.append((p4_file, stf_file, TestResult.PASS))
        else:
            results.append((p4_file, stf_file, TestResult.FAIL))

    return results


def run_hol4p4_dynamic(test_suite_start_dir: str):
    project_root = "/HOL4P4/hol/p4_from_json/"

    src_dir = Path(test_suite_start_dir).resolve()

    test_suite_path = project_root + test_suite_start_dir.removeprefix("/").replace(
        "/", "-"
    )
    test_suite_dir = Path(test_suite_path).resolve()

    # patch all stfs in src_dir, which will end up in dst_dir
    patch_directory(src_dir, test_suite_dir)

    test_suite_path = str(test_suite_dir.resolve())
    test_suite = read_test_suite(
        test_suite_path,
        "/testdata/excludes",
        ignore_list=["static/bug"],
        additional_list=["/HOL4P4/hol4p4.exclude"],
    )

    # move over excluded files to another directory before running batch test
    exclude_camp = Path(test_suite_path + ".excluded").resolve()
    exclude_camp.mkdir(parents=True, exist_ok=True)
    for f in test_suite.excluded:
        shutil.move(test_suite_dir / f, exclude_camp)

    command = ["./run-tests.sh", test_suite_path]

    result = subprocess.run(
        command,
        cwd=project_root,
    )

    results = hol4p4_collect_test_results(test_suite_path, test_suite)
    dump_json(
        results, "/HOL4P4", test_suite_start_dir.removeprefix("/").replace("/", "-")
    )


def run_p4spectec_dynamic(test_suite: TestSuite, arch_: Arch):
    arch = arch_.value.lower()

    tests = test_suite.pairs
    excluded = test_suite.excluded

    results = []

    project_root = "/p4-spectec"

    for p4_path, stf_path in tests:
        print(f"{p4_path}\t{stf_path}", end=" ")

        if is_exclude_pair(excluded, (p4_path, stf_path)):
            results.append((p4_path, stf_path, TestResult.SKIP))
            print("[SKIP]")
            continue

        watsup_files = sorted(glob.glob("/p4-spectec/spec-concrete/*/*.watsup"))

        command = (
            ["./p4spectec", "sim"]
            + watsup_files
            + [
                "-i",
                "/p4include",
                "-arch",
                arch,
                "-sl",
                "-p",
                p4_path,
                "-stf",
                stf_path,
            ]
        )

        result = subprocess.run(
            command,
            cwd=project_root,
            stdout=subprocess.DEVNULL,
        )

        if result.returncode == 0:
            results.append((p4_path, stf_path, TestResult.PASS))
            print("[PASS]")
        else:
            results.append((p4_path, stf_path, TestResult.FAIL))
            print("[FAIL]")

    print(results)
    print(len(results))


def run_petr4_dynamic(test_suite: TestSuite):
    pass

    tests = test_suite.pairs
    excluded = test_suite.excluded

    results = []

    project_root = "/p4-spectec"

    for p4_path, stf_path in tests:
        print(f"{p4_path}\t{stf_path}", end=" ")

        if is_exclude_pair(excluded, (p4_path, stf_path)):
            results.append((p4_path, stf_path, TestResult.SKIP))
            print("[SKIP]")
            continue

        watsup_files = sorted(glob.glob("/p4-spectec/spec-concrete/*/*.watsup"))

        command = (
            ["./p4spectec", "sim"]
            + watsup_files
            + [
                "-i",
                "/p4include",
                "-arch",
                arch,
                "-sl",
                "-p",
                p4_path,
                "-stf",
                stf_path,
            ]
        )

        result = subprocess.run(
            command,
            cwd=project_root,
            stdout=subprocess.DEVNULL,
        )

        if result.returncode == 0:
            results.append((p4_path, stf_path, TestResult.PASS))
            print("[PASS]")
        else:
            results.append((p4_path, stf_path, TestResult.FAIL))
            print("[FAIL]")

    print(results)
    print(len(results))


positive_test_suite = read_test_suite(
    "/testdata/p4_16_samples", "/testdata/excludes/static", ignore_list=["bug/"]
)

negative_test_suite = read_test_suite(
    "/testdata/p4_16_errors", "/testdata/excludes/static", ignore_list=["bug/"]
)

negative_test_suite_petr4 = read_test_suite(
    "/testdata/p4_16_errors",
    "/testdata/excludes/static",
    ignore_list=["bug/"],
    additional_list=["/petr4/petr4.exclude"],
)


def run_static():
    run_p4spectec_static(positive_test_suite, StaticTestType.POS)
    run_p4spectec_static(negative_test_suite, StaticTestType.NEG)
    run_petr4_static(positive_test_suite, StaticTestType.POS)
    run_petr4_static(negative_test_suite_petr4, StaticTestType.NEG)


# v1model_test_suite = read_test_suite("/testdata/p4testgen/v1model", "/testdata/excludes", ["static/bug"])
# run_p4spectec_dynamic(v1model_test_suite, "v1model")

# run_hol4p4_dynamic("/testdata/p4c/ebpf")
# v1model_test_suite = read_test_suite("/testdata/p4testgen/v1model", "/testdata/excludes", ["static/bug"])

# test_suite = read_test_suite_("/testdata/p4testgen/v1model/", "/testdata/excludes", ignore_list=["static/bug"], additional_list=["/HOL4P4/hol4p4.exclude"])
# print(len(test_suite.excluded))
