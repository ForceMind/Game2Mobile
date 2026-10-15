#!/usr/bin/env python3
"""Local-only M1 validation of the *real* Game2Mobile DmIOS app.

Unlike public Actions checks, a user-controlled Apple Silicon Mac can access
its owner's licensed ExeFS/RomFS and Apple signing. This script NEVER uploads
them. Do not run this workflow on hosted GitHub runners or publish its logs.

Safe preview on any machine:
    python3 scripts/m1_local_pipeline.py plan

After arranging private game files and Xcode locally:
    python3 scripts/m1_local_pipeline.py all --profile metal4

Individual stages: preflight, prepare, headers, verify, build.
An optional --profile m3 switches the real build to the iOS 18 Metal M3 path.
Outputs and logs are stored under DM_ROOT/m1-private-evidence, outside Git.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import plistlib
import subprocess
import sys
import tempfile

try:
    from .private_build_inputs import inspect_private_headers, PrivateInputError
except ImportError:  # Invoked as a standalone script from the repository root.
    from private_build_inputs import inspect_private_headers, PrivateInputError

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = (ROOT / "dm/PRODUCT").read_text(encoding="utf-8").strip()
HEADER_NAMES = ("dm_vault_tab.h", "dm_hud_exp.h", "dm_bright_levels.inc")
STAGE_COMMANDS = ("preflight", "prepare", "headers", "verify", "build")


class StageError(RuntimeError):
    def __init__(self, stage: str, hint: str):
        super().__init__(hint)
        self.stage = stage


def workspace_is_safe(path: Path) -> bool:
    """Private evidence and game assets should never live in the checkout."""
    return not path.expanduser().resolve().is_relative_to(ROOT.resolve())


def new_private_evidence_dir(workspace: Path, commit: str, profile: str) -> Path:
    """Create a never-reused, private build run; reject symlinked destinations."""
    root = workspace / "m1-private-evidence"
    parent = root / commit[:12] / profile
    for directory in (root, root / commit[:12], parent):
        if directory.is_symlink() or not workspace_is_safe(directory):
            raise StageError("environment", "Private evidence directory resolves inside Git or through a symlink")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
    os.chmod(output, 0o700)
    return output


def private_environment(
    base: dict[str, str], workspace: Path, romfs: Path,
    profile: str, evidence: Path
) -> dict[str, str]:
    """Force a fresh App build, ignoring dangerous inherited shortcut flags."""
    env = base.copy()
    for key in ("DM_GEN_ONLY", "DM_OUT", "DM_IOS_DD", "DM_NOINSTALL"):
        env.pop(key, None)
    env["DM_ROOT"] = str(workspace)
    env["DM_ROMFS_SRC"] = str(romfs)
    env["DM_IOS_M3"] = "1" if profile == "m3" else "0"
    env["DM_IOS_DD"] = str(evidence / "derived-data")
    return env


def write_private_json(path: Path, data: dict) -> None:
    """Create the metadata file in restrictive mode, never overwrite a prior run."""
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(data, output, indent=2, ensure_ascii=False)
        output.write("\n")


def build_plan(profile: str) -> tuple[tuple[str, str], ...]:
    return (
        ("preflight", "./setup.sh check (Apple tools, game hashes, local signing)"),
        ("prepare", "./setup.sh (prepare rewritten modules and shader cache locally)"),
        ("headers", "make -C dm/host dm_vault_tab.h dm_hud_exp.h dm_bright_levels.inc"),
        ("verify", "strict real iPhoneOS Clang, 91/91 source files with private headers"),
        ("build", "dm/ios/run.sh build (actual signed DmIOS game target; no installation)"),
    )


def checked_platform() -> None:
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise StageError("environment", "This workflow needs an Apple Silicon Mac")


def tracked_clean() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if result.returncode or result.stdout.strip():
        raise StageError(
            "environment", "Tracked source has local modifications; build from a clean commit"
        )


def head_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if result.returncode or len(result.stdout.strip()) != 40:
        raise StageError("environment", "Cannot identify the Git commit to validate")
    return result.stdout.strip()


def ignored_headers() -> bool:
    return all(
        subprocess.run(
            ["git", "check-ignore", "-q", f"dm/host/{name}"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
        for name in HEADER_NAMES
    )


def execute(stage: str, command: list[str], *, cwd: Path,
            env: dict[str, str], evidence_dir: Path) -> None:
    logfile = evidence_dir / f"{stage}.private.log"
    descriptor = os.open(
        str(logfile), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as out:
        out.write(f"Game2Mobile private stage: {stage}\n")
        out.flush()
        try:
            result = subprocess.run(
                command, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT,
                check=False,
            )
        except OSError as exc:
            raise StageError(stage, f"Unable to start stage: {type(exc).__name__}") from exc
    if result.returncode != 0:
        raise StageError(stage, "See its local-only private log for details")


def build_record(commit: str, profile: str) -> dict:
    return {
        "project": "Game2Mobile",
        "product": PRODUCT,
        "source_commit": commit,
        "profile": profile,
        "scope": "local-private-licensed-game-build",
        "report_contains_game_data": False,
        "report_contains_keys_or_device_identifiers": False,
        "uploaded_anything": False,
        "source_objects_expected": 91,
        "source_objects_compiled": None,
        "end_to_end_build_stages_verified": False,
        "full_game_app_built": False,
        "app_signed_locally": False,
        "physical_device_installed": False,
        "physical_device_gameplay_tested": False,
        "steps": {},
        "result": "incomplete",
    }


def validate_app(app: Path) -> bool:
    executable = app / "DmIOS"
    info_path = app / "Info.plist"
    if not executable.is_file() or not info_path.is_file():
        raise StageError("build", "Xcode did not produce a complete DmIOS.app")
    try:
        info = plistlib.loads(info_path.read_bytes())
    except (OSError, ValueError, plistlib.InvalidFileException) as exc:
        raise StageError("build", "Cannot validate the built App Info.plist") from exc
    if info.get("CFBundleDisplayName") != "Game2Mobile":
        raise StageError("build", "Built App has an unexpected display name")
    arch = subprocess.run(
        ["lipo", "-archs", str(executable)],
        capture_output=True, text=True,
    )
    if arch.returncode or "arm64" not in arch.stdout.split():
        raise StageError("build", "Built Game2Mobile executable is not ARM64")
    sign = subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(app)],
        capture_output=True, text=True,
    )
    if sign.returncode:
        raise StageError(
            "build", "App compiled but the local Apple code signature did not verify"
        )
    return True


def run_pipeline(action: str, profile: str, workspace: Path,
                 romfs: Path) -> dict:
    if not workspace_is_safe(workspace):
        raise StageError("environment", "DM_ROOT must be outside the Git checkout")
    if action != "plan" and not workspace_is_safe(romfs):
        raise StageError("environment", "Licensed RomFS files must not be inside Git")
    # setup.sh check still verifies the canonical workspace game directory.
    # A custom --romfs is intentionally supported for just the header stage,
    # not the whole setup/build chain until setup.sh itself supports it.
    standard_romfs = (
        workspace / "data/switch/3.3.94012/Update/RomFS"
    ).resolve()
    if action in {"all", "preflight", "prepare", "build"} and romfs != standard_romfs:
        raise StageError(
            "environment",
            "Full setup requires the canonical DM_ROOT game directory; "
            "use --romfs only with headers/verify",
        )
    if action != "plan":
        checked_platform()
        tracked_clean()
        if not ignored_headers():
            raise StageError(
                "environment", "Generated game headers are not all covered by .gitignore"
            )
    if action == "plan":
        # A plan neither opens the game files nor creates output directories.
        for stage, description in build_plan(profile):
            print(f"{stage:10} {description}")
        print("No hosted CI uploads. No signed or playable App is claimed by a plan.")
        return {}

    commit = head_sha()
    evidence = new_private_evidence_dir(workspace, commit, profile)
    env = private_environment(os.environ, workspace, romfs, profile, evidence)
    venv_bin = workspace / "build/cache/dm/venv/bin"
    if venv_bin.is_dir():
        env["PATH"] = str(venv_bin) + os.pathsep + env.get("PATH", "")
    record = build_record(commit, profile)
    stages = STAGE_COMMANDS if action == "all" else (action,)

    try:
        for stage in stages:
            print(f"Running local-only M1 stage: {stage}", flush=True)
            if stage == "preflight":
                execute(stage, ["bash", "setup.sh", "check"],
                        cwd=ROOT, env=env, evidence_dir=evidence)
            elif stage == "prepare":
                execute(stage, ["bash", "setup.sh"], cwd=ROOT,
                        env=env, evidence_dir=evidence)
                venv_bin = workspace / "build/cache/dm/venv/bin"
                if venv_bin.is_dir():
                    env["PATH"] = str(venv_bin) + os.pathsep + env.get("PATH", "")
            elif stage == "headers":
                # Always rebuild tables: make timestamps alone cannot detect
                # a replaced RomFS at the same configured source path.
                execute(
                    stage,
                    ["make", "-B", "-s", "-C", "dm/host", *HEADER_NAMES,
                     "ROMFS=" + str(romfs)],
                    cwd=ROOT, env=env, evidence_dir=evidence,
                )
                try:
                    inspect_private_headers(ROOT / "dm/host")
                except PrivateInputError as exc:
                    raise StageError("headers", str(exc)) from exc
            elif stage == "verify":
                private_report = evidence / "private-compile.json"
                execute(
                    stage,
                    [sys.executable, "scripts/ci_production_compile.py",
                     "--profiles", profile, "--strict", "--private-derived-headers",
                     str(ROOT / "dm/host"), "--report", str(private_report)],
                    cwd=ROOT, env=env, evidence_dir=evidence,
                )
                comp = json.loads(private_report.read_text(encoding="utf-8"))
                compiled = comp["profiles"][profile].get("compiled", 0)
                if compiled != comp["sources_per_profile"] or compiled != 91:
                    raise StageError("verify", "Strict private compile did not reach 91/91")
                record["source_objects_compiled"] = compiled
            elif stage == "build":
                # Fail closed on stale outputs and inherited shortcut switches.
                # Each invocation has a unique, newly allocated DerivedData path.
                derived = Path(env["DM_IOS_DD"])
                if derived.exists() or env.get("DM_GEN_ONLY") == "1":
                    raise StageError("build", "A fresh full App build is required")
                execute(stage, ["bash", "run.sh", "build"], cwd=ROOT / "dm/ios",
                        env=env, evidence_dir=evidence)
                app = derived / "Build/Products/Release-iphoneos/DmIOS.app"
                record["app_signed_locally"] = validate_app(app)
                record["full_game_app_built"] = True
            else:
                raise StageError("arguments", "Unknown stage")
            record["steps"][stage] = "passed"
        record["end_to_end_build_stages_verified"] = action == "all"
        record["result"] = "passed" if action == "all" else "partial"
        return record
    except StageError as error:
        record["steps"][error.stage] = "failed"
        record["result"] = "failed"
        raise
    finally:
        # This JSON is metadata only. Raw generated headers, compiled game
        # objects, shader binaries and signature material are NEVER uploaded.
        summary = evidence / "m1-summary.json"
        write_private_json(summary, record)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage", choices=("plan", *STAGE_COMMANDS, "all"),
        help="Plan safely or perform specific owner-only build stages",
    )
    parser.add_argument("--profile", choices=("metal4", "m3"), default="metal4")
    workspace = Path(
        os.environ.get("DM_ROOT", str(Path.home() / "dm-work"))
    ).expanduser()
    parser.add_argument("--workspace", type=Path, default=workspace)
    parser.add_argument("--romfs", type=Path, default=None,
                        help="Locally owned version-matched RomFS (not uploaded)")
    args = parser.parse_args()
    work = args.workspace.expanduser().resolve()
    romfs = (args.romfs or Path(os.environ.get(
        "DM_ROMFS_SRC", str(work / "data/switch/3.3.94012/Update/RomFS")
    ))).expanduser().resolve()
    try:
        report = run_pipeline(args.stage, args.profile, work, romfs)
    except StageError as error:
        print(
            f"M1 {error.stage} failed: {error}. Raw logs stay on the owner Mac "
            "(outside this Git repository).",
            file=sys.stderr,
        )
        return 1
    if args.stage != "plan":
        print(
            "Local M1 stage(s) passed. Metadata-only JSON is in DM_ROOT/"
            "m1-private-evidence. This does not establish device gameplay."
        )
        if report["full_game_app_built"]:
            print("Signed local Game2Mobile DmIOS.app verified (NOT uploaded).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
