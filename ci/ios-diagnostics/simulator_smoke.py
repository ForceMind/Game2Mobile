#!/usr/bin/env python3
"""Install and launch the NON-PLAYABLE Game2Mobile diagnostics app in an iOS Simulator."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path


def run(*arguments: str, timeout: int = 180) -> str:
    result = subprocess.run(
        ["xcrun", "simctl", *arguments],
        text=True, capture_output=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"simctl {arguments[0]} failed ({result.returncode}): "
            f"{result.stderr[-1000:]}"
        )
    return result.stdout.strip()


def device_version(runtime_name: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", runtime_name)
    return tuple(map(int, parts[-2:])) if parts else (0,)


def select_simulator(info: dict) -> tuple[str, str, str, str]:
    matches = []
    for runtime, devices in info.get("devices", {}).items():
        if "iOS" not in runtime:
            continue
        for device in devices:
            if not device.get("isAvailable") or "iPhone" not in device.get("name", ""):
                continue
            matches.append((
                device_version(runtime),
                device.get("name", ""),
                device["udid"],
                runtime,
                device.get("state", "Shutdown"),
            ))
    if not matches:
        raise RuntimeError("No available iOS iPhone Simulator on Apple build runner")
    matches.sort(reverse=True)
    _, name, identifier, runtime, state = matches[0]
    return name, identifier, runtime, state


def smoke(app: Path, destination: Path) -> dict:
    if not app.is_dir() or not (app / "Info.plist").is_file():
        raise RuntimeError("Expected compiled Simulator .app")
    destination.mkdir(parents=True, exist_ok=True)
    info = json.loads(run("list", "-j", "devices", "available"))
    name, identifier, runtime, state = select_simulator(info)
    print(f"Using {name}, runtime {runtime}, initial state {state}", flush=True)
    was_booted = state == "Booted"
    try:
        if not was_booted:
            run("boot", identifier, timeout=90)
        run("bootstatus", identifier, "-b", timeout=240)
        run("install", identifier, str(app), timeout=120)
        launch = run("launch", identifier, "com.game2mobile.diagnostics.smoke", timeout=120)
        if not re.search(r"com\.game2mobile\.diagnostics\.smoke:\s*\d+", launch):
            raise RuntimeError(f"App launch did not return a PID: {launch}")
        print(f"App launched: {launch}", flush=True)
        time.sleep(3)
        screenshot = destination / "simulator-launched-diagnostics.png"
        run("io", identifier, "screenshot", str(screenshot), timeout=90)
        if not screenshot.is_file() or not screenshot.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("Simulator screenshot missing or not a PNG")
        result = {
            "kind": "non-playable-game2mobile-diagnostics-runtime-smoke",
            "simulator_name": name,
            "simulator_runtime": runtime,
            "install_succeeded": True,
            "launch_pid_returned": True,
            "screenshot_captured": True,
            "screenshot_file": screenshot.name,
            "game_runtime_tested": False,
            "physical_device_tested": False,
        }
        (destination / "simulator-runtime.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        return result
    finally:
        try:
            run("terminate", identifier, "com.game2mobile.diagnostics.smoke", timeout=30)
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
        if not was_booted:
            try:
                run("shutdown", identifier, timeout=30)
            except (RuntimeError, subprocess.TimeoutExpired):
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(smoke(args.app.resolve(), args.output.resolve()), indent=2))


if __name__ == "__main__":
    main()
