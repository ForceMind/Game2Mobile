#!/usr/bin/env python3
"""Bind staged iOS inputs to the guest bytes in the final DmIOS executable.

The manifest contains hashes and public version metadata, never game bytes,
owner paths, signing identities or device IDs. It is a consistency check, not
a signature, a RomFS inventory, or proof that the game can run. Dirty source
is recorded explicitly and cannot pass the owner's clean-source M1 gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "game2mobile.build-identity.v1"
MODULES = ("main", "sdk")
PROFILES = ("metal4", "m3")
PAGE = 0x4000
MANIFEST = "dm/build_identity.json"
RUNTIME_FILES = tuple(
    f"dm/{name}.{suffix}" for name in MODULES
    for suffix in ("fixups.tsv", "gates.tsv", "cuts.tsv")
) + ("dm/shader_map.tsv", "dm/pso_manifest.tsv", "dm/c1_full.tsv")
OPTIONAL_FILES = ("dm/bootlist.tsv",)
MAX_MANIFEST = 128 * 1024


class IdentityError(ValueError):
    """An input, manifest or embedded image cannot be identified consistently."""


def _hex(value: object, length: int) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d}" % length, value) is not None


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError) as exc:
        raise IdentityError("Build identity contains unsupported or excessively nested values") from exc


def fingerprint(manifest: dict) -> str:
    return hashlib.sha256(_canonical({k: v for k, v in manifest.items() if k != "fingerprint"})).hexdigest()


def _file(root: Path, relative: str, *, empty: bool = False) -> Path:
    """Only fixed, local bundle paths; reject symlinks in every component."""
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p in (".", "..") for p in parts):
        raise IdentityError("Invalid build identity resource path")
    current = root
    if root.is_symlink() or not root.is_dir():
        raise IdentityError("Build identity root is missing or symlinked")
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise IdentityError(f"Symlinked build identity input: {relative}")
    if not current.is_file() or (not empty and current.stat().st_size == 0):
        raise IdentityError(f"Missing or empty build identity input: {relative}")
    return current


def _hash_range(path: Path, offset: int, length: int, *, padding: int = 0) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        stream.seek(offset)
        remaining = length
        while remaining:
            chunk = stream.read(min(1024 * 1024, remaining))
            if not chunk:
                raise IdentityError("Truncated build identity input")
            digest.update(chunk)
            remaining -= len(chunk)
    while padding:
        size = min(padding, 1024 * 1024)
        digest.update(bytes(size))
        padding -= size
    return digest.hexdigest()


def _digest(path: Path) -> dict:
    size = path.stat().st_size
    return {"size": size, "sha256": _hash_range(path, 0, size)}


def source_state(repo: Path) -> dict:
    def git(*args: str) -> str:
        result = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True)
        if result.returncode:
            raise IdentityError("Cannot identify source checkout")
        return result.stdout.strip()
    commit = git("rev-parse", "--verify", "HEAD")
    if not _hex(commit, 40):
        raise IdentityError("Invalid source commit")
    # Xcode includes the whole Sources directory, including nonignored new
    # files. A clean claim must therefore include untracked source too.
    return {"commit": commit, "dirty": bool(git("status", "--porcelain", "--untracked-files=all"))}


def source_versions(repo: Path) -> dict:
    product = _file(repo, "dm/PRODUCT").read_text(encoding="utf-8").strip()
    if re.fullmatch(r"[A-Za-z0-9._-]{1,80}", product) is None:
        raise IdentityError("Invalid tracked product version")
    chain_text = _file(repo, "dm/gfx/nvn/dmsh_chain.h").read_text(encoding="utf-8")
    chain = re.search(r'^#define DMSH_CHAIN "([a-f0-9]{12})"\s*$', chain_text, re.M)
    rewriter = _file(repo, "dm/tools/patch_nso.py")
    pinned = re.search(r"^RULE_BUILD\s*=\s*'([a-f0-9]{32})'", rewriter.read_text(encoding="utf-8"), re.M)
    if chain is None or pinned is None:
        raise IdentityError("Tracked shader chain or pinned game build ID is missing")
    return {"product": product, "shader_chain": chain[1],
            "rewriter_sha256": _digest(rewriter)["sha256"], "main_build_id": pinned[1]}


def _build_id(path: Path) -> str:
    found = re.findall(r"^# BUILD_ID\s+([0-9a-f]{32})\s*$", path.read_text(encoding="utf-8"), re.M)
    if len(found) != 1:
        raise IdentityError("Module cuts table must identify exactly one game build")
    return found[0]


def _module_identity(out: Path, stage: Path, module: str) -> dict:
    image = _file(out, module + ".patched.bin")
    fixups = _file(out, module + ".fixups.tsv")
    headers: dict[str, int] = {}
    for line in fixups.read_text(encoding="utf-8").splitlines():
        if not line.startswith("# "):
            continue
        fields = line[2:].split()
        if len(fields) != 2 or fields[0] in headers:
            raise IdentityError("Invalid or duplicate module layout header")
        try:
            headers[fields[0]] = int(fields[1], 0)
        except ValueError as exc:
            raise IdentityError("Invalid module layout number") from exc
    required = ("TEXT_END", "PATCH_OFF", "KEY_PAGE_OFF", "KEY_PAGE_SIZE")
    if any(key not in headers for key in required):
        raise IdentityError("Incomplete module layout")
    te, po, ko, ks = (headers[key] for key in required)
    size = image.stat().st_size
    a, end = (te + PAGE - 1) // PAGE * PAGE, (size + PAGE - 1) // PAGE * PAGE
    if not (0 < te <= a <= ko and ko + ks <= po < size and ks == PAGE
            and ko % PAGE == 0 and po % PAGE == 0):
        raise IdentityError("Module layout does not match signed 16 KiB embedding")
    for suffix in ("fixups.tsv", "gates.tsv", "cuts.tsv"):
        relative = f"{module}.{suffix}"
        before = _digest(_file(out, relative, empty=suffix == "gates.tsv"))
        after = _digest(_file(stage, "dm/" + relative, empty=suffix == "gates.tsv"))
        if before != after:
            raise IdentityError(f"Staged module table differs from its image inputs: {relative}")
    sections = []
    # Match gen_embed.py, including zero padding in the final executable.
    for segment, section, lo, hi in (
        ("__TEXT", f"__dm{module}x0", 0, a),
        (f"__DM{module}W", "__img", a, po),
        ("__TEXT", f"__dm{module}x1", po, end),
    ):
        count = min(hi, size) - lo
        sections.append({"segment": segment, "section": section, "size": hi - lo,
                         "sha256": _hash_range(image, lo, count, padding=hi - lo - count)})
    return {"build_id": _build_id(_file(out, module + ".cuts.tsv")),
            "image_size": size, "image_sha256": _digest(image)["sha256"], "sections": sections}


def _shader_cache(root: Path, chain: str) -> dict:
    directory = root / "msl" / ("b-" + chain)
    if (root / "msl").is_symlink() or directory.is_symlink() or not directory.is_dir():
        raise IdentityError("Current shader cache is absent or symlinked")
    digest = hashlib.sha256()
    count = 0
    for path in sorted(directory.iterdir(), key=lambda p: p.name):
        # Xcode's builtin-copy excludes Finder metadata from folder resources.
        # It is not shader input and must not make a valid packaged cache stale.
        if path.name == ".DS_Store":
            continue
        if re.fullmatch(r"[A-Za-z0-9_.-]+", path.name) is None:
            raise IdentityError("Unexpected shader cache filename")
        item = _digest(_file(directory, path.name))
        digest.update(_canonical({"name": path.name, **item}) + b"\n")
        count += 1
    if not count:
        raise IdentityError("Current shader cache is empty")
    return {"file_count": count, "sha256": digest.hexdigest()}


def create_identity(repo: Path, out: Path, stage: Path, profile: str) -> dict:
    if profile not in PROFILES:
        raise IdentityError("Unknown build profile")
    versions = source_versions(repo)
    if (out / ".product-building").exists():
        raise IdentityError("Module product build is still in progress")
    for marker in ("build_src.sha256", "product.complete.sha256"):
        words = _file(out, marker).read_text(encoding="utf-8").split()
        if not words or words[0] != versions["rewriter_sha256"]:
            raise IdentityError("Module product was built with a different rewriter; rerun setup")
    modules = {name: _module_identity(out, stage, name) for name in MODULES}
    if modules["main"]["build_id"] != versions.pop("main_build_id"):
        raise IdentityError("Game main build ID does not match the pinned rewriter")
    files = {name: _digest(_file(stage, name, empty=name.endswith(".gates.tsv")))
             for name in RUNTIME_FILES}
    for name in OPTIONAL_FILES:
        if (stage / name).exists() or (stage / name).is_symlink():
            files[name] = _digest(_file(stage, name))
    # Bind shader tables to this checkout, not a stale Gen directory.
    for name in ("shader_map.tsv", "pso_manifest.tsv", "c1_full.tsv"):
        if files["dm/" + name] != _digest(_file(repo, "dm/gfx/nvn/" + name)):
            raise IdentityError("Staged shader tables differ from tracked source")
    result = {"schema": SCHEMA, "source": source_state(repo), **versions,
              "profile": profile, "modules": modules, "runtime_files": files,
              "shader_cache": _shader_cache(stage, versions["shader_chain"])}
    result["fingerprint"] = fingerprint(result)
    return result


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise IdentityError("Duplicate key in build identity")
        result[key] = value
    return result


def read_identity(app: Path) -> dict:
    path = _file(app, MANIFEST)
    if path.stat().st_size > MAX_MANIFEST:
        raise IdentityError("Oversized build identity manifest")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise IdentityError("Malformed build identity manifest") from exc
    if (not isinstance(value, dict) or value.get("schema") != SCHEMA
            or not _hex(value.get("fingerprint"), 64) or fingerprint(value) != value["fingerprint"]):
        raise IdentityError("Invalid build identity schema or fingerprint")
    return value


def guest_sections(executable: Path) -> dict[tuple[str, str], tuple[int, int]]:
    """Read bounded thin ARM64 Mach-O load commands; never invoke game code."""
    expected = {("__TEXT", f"__dm{m}x{x}") for m in MODULES for x in (0, 1)}
    expected.update((f"__DM{m}W", "__img") for m in MODULES)
    size = executable.stat().st_size
    with executable.open("rb") as stream:
        header = stream.read(32)
        if len(header) != 32:
            raise IdentityError("Truncated Mach-O header")
        magic, cpu, _, filetype, ncmds, cmdsize, _, _ = struct.unpack("<8I", header)
        if magic != 0xFEEDFACF or cpu != 0x0100000C or filetype != 2:
            raise IdentityError("Expected a thin ARM64 Mach-O executable")
        if not 0 < ncmds <= 65536 or not ncmds * 8 <= cmdsize <= min(size - 32, 16 * 1024 * 1024):
            raise IdentityError("Invalid Mach-O load command bounds")
        commands = stream.read(cmdsize)
    offset = 0
    found = {}
    for _ in range(ncmds):
        if offset + 8 > len(commands):
            raise IdentityError("Truncated Mach-O load command")
        command, length = struct.unpack_from("<II", commands, offset)
        if length < 8 or length % 8 or offset + length > len(commands):
            raise IdentityError("Invalid Mach-O load command length")
        if command == 0x19:  # LC_SEGMENT_64
            if length < 72:
                raise IdentityError("Truncated Mach-O segment")
            segment = struct.unpack_from("<II16sQQQQiiII", commands, offset)
            segname = segment[2].split(b"\0", 1)[0]
            fileoff, filesize, initprot, nsects = segment[5], segment[6], segment[8], segment[9]
            if 72 + nsects * 80 != length or fileoff + filesize > size:
                raise IdentityError("Invalid Mach-O segment bounds")
            for index in range(nsects):
                row = struct.unpack_from("<16s16sQQ8I", commands, offset + 72 + index * 80)
                name_bytes, seg_bytes = row[0].split(b"\0", 1)[0], row[1].split(b"\0", 1)[0]
                try:
                    key = (seg_bytes.decode("ascii"), name_bytes.decode("ascii"))
                except UnicodeError as exc:
                    raise IdentityError("Invalid Mach-O section name") from exc
                if key not in expected:
                    continue
                length_in_file, start, section_type = row[3], row[4], row[8] & 0xFF
                required_prot = 5 if key[0] == "__TEXT" else 3
                if (key in found or segname != seg_bytes or section_type != 0
                        or initprot != required_prot or not length_in_file
                        or length_in_file % PAGE or start < max(fileoff, 32 + cmdsize)
                        or start + length_in_file > fileoff + filesize):
                    raise IdentityError("Invalid, duplicate or misplaced guest Mach-O section")
                found[key] = (start, length_in_file)
        offset += length
    if offset != len(commands) or set(found) != expected:
        raise IdentityError("Missing guest sections or inconsistent Mach-O commands")
    ranges = sorted(found.values())
    if any(a + size_a > b for (a, size_a), (b, _) in zip(ranges, ranges[1:])):
        raise IdentityError("Overlapping guest Mach-O sections")
    return found


def verify_identity(app: Path, profile: str, *, repo: Path = ROOT,
                    expected_commit: str | None = None, require_clean: bool = False) -> dict:
    value = read_identity(app)
    if profile not in PROFILES or value.get("profile") != profile:
        raise IdentityError("Build identity Metal profile mismatch")
    source = source_state(repo)
    if expected_commit is not None and source["commit"] != expected_commit:
        raise IdentityError("Source commit changed during build verification")
    declared = value.get("source")
    if (not isinstance(declared, dict) or type(declared.get("dirty")) is not bool
            or declared != source or (require_clean and source["dirty"])):
        raise IdentityError("Build identity source commit or clean-state mismatch")
    versions = source_versions(repo)
    for key in ("product", "shader_chain", "rewriter_sha256"):
        if value.get(key) != versions[key]:
            raise IdentityError("Build identity product, rewriter or shader chain mismatch")
    files = value.get("runtime_files")
    if (not isinstance(files, dict) or not set(RUNTIME_FILES).issubset(files)
            or not set(files).issubset(set(RUNTIME_FILES + OPTIONAL_FILES))):
        raise IdentityError("Incomplete build identity runtime file inventory")
    for name, digest in files.items():
        if _digest(_file(app, name, empty=name.endswith(".gates.tsv"))) != digest:
            raise IdentityError(f"Bundled runtime file hash mismatch: {name}")
    for name in OPTIONAL_FILES:
        if name not in files and ((app / name).exists() or (app / name).is_symlink()):
            raise IdentityError("Unexpected optional runtime file absent from build identity")
    for name in ("shader_map.tsv", "pso_manifest.tsv", "c1_full.tsv"):
        if files["dm/" + name] != _digest(_file(repo, "dm/gfx/nvn/" + name)):
            raise IdentityError("Bundled shader tables differ from tracked source")
    if _shader_cache(app, versions["shader_chain"]) != value.get("shader_cache"):
        raise IdentityError("Bundled shader cache hash mismatch")
    modules = value.get("modules")
    if not isinstance(modules, dict) or set(modules) != set(MODULES):
        raise IdentityError("Incomplete build identity module inventory")
    executable = _file(app, "DmIOS")
    actual = guest_sections(executable)
    for name in MODULES:
        record = modules[name]
        if (not isinstance(record, dict) or not _hex(record.get("build_id"), 32)
                or not _hex(record.get("image_sha256"), 64)
                or type(record.get("image_size")) is not int or record["image_size"] <= 0):
            raise IdentityError("Invalid build identity module metadata")
        if _build_id(_file(app, f"dm/{name}.cuts.tsv")) != record["build_id"]:
            raise IdentityError("Bundled module build ID mismatch")
        if name == "main" and record["build_id"] != versions["main_build_id"]:
            raise IdentityError("Bundled game build does not match pinned rewriter")
        sections = record.get("sections")
        if not isinstance(sections, list) or len(sections) != 3:
            raise IdentityError("Incomplete build identity section inventory")
        expected = {("__TEXT", f"__dm{name}x0"), ("__TEXT", f"__dm{name}x1"), (f"__DM{name}W", "__img")}
        seen = set()
        for section in sections:
            if not isinstance(section, dict):
                raise IdentityError("Malformed build identity section")
            key = (section.get("segment"), section.get("section"))
            if not all(isinstance(part, str) for part in key) or key not in expected or key in seen:
                raise IdentityError("Duplicate or unexpected build identity section")
            seen.add(key)
            offset, size = actual[key]
            if (type(section.get("size")) is not int or section["size"] != size
                    or not _hex(section.get("sha256"), 64)
                    or _hash_range(executable, offset, size) != section["sha256"]):
                raise IdentityError(f"Embedded guest section hash mismatch: {name}")
        ordered = [actual[("__TEXT", f"__dm{name}x0")],
                   actual[(f"__DM{name}W", "__img")],
                   actual[("__TEXT", f"__dm{name}x1")]]
        padded_size = sum(size for _, size in ordered)
        image_size = record["image_size"]
        if not (padded_size - ordered[-1][1] < image_size <= padded_size
                and (image_size + PAGE - 1) // PAGE * PAGE == padded_size):
            raise IdentityError("Embedded guest image size is inconsistent with its sections")
        digest = hashlib.sha256()
        remaining = image_size
        with executable.open("rb") as stream:
            for offset, length in ordered:
                stream.seek(offset)
                while length:
                    chunk = stream.read(min(1024 * 1024, length))
                    if not chunk:
                        raise IdentityError("Truncated embedded guest image")
                    valid = min(remaining, len(chunk))
                    digest.update(chunk[:valid])
                    if any(chunk[valid:]):
                        raise IdentityError("Nonzero embedded guest image padding")
                    remaining -= valid
                    length -= len(chunk)
        if digest.hexdigest() != record["image_sha256"]:
            raise IdentityError("Embedded guest image hash mismatch")
    return {"build_identity_verified": True, "build_identity_fingerprint": value["fingerprint"],
            "build_identity_source_clean": not source["dirty"],
            "embedded_guest_bytes_verified": True, "bundled_shader_bytes_verified": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "verify"))
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--profile", choices=PROFILES, required=True)
    parser.add_argument("--modules", type=Path)
    parser.add_argument("--stage", type=Path)
    parser.add_argument("--app", type=Path)
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "create":
            if args.modules is None or args.stage is None:
                parser.error("create requires --modules and --stage")
            value = create_identity(args.repo, args.modules, args.stage, args.profile)
            if args.require_clean and value["source"]["dirty"]:
                raise IdentityError("Clean source is required")
            destination = args.stage / MANIFEST
            if destination.is_symlink():
                raise IdentityError("Symlinked build identity output")
            # Gen is freshly staged by run.sh; replace atomically after all checks.
            temporary = destination.with_suffix(".tmp")
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(value, stream, sort_keys=True, indent=2)
                stream.write("\n")
            temporary.replace(destination)
            result = {"build_identity_created": True, "fingerprint": value["fingerprint"],
                      "source_clean": not value["source"]["dirty"]}
        else:
            if args.app is None:
                parser.error("verify requires --app")
            result = verify_identity(args.app, args.profile, repo=args.repo, require_clean=args.require_clean)
    except (IdentityError, OSError, UnicodeError) as exc:
        # OSError may contain a private absolute path; never echo that text.
        message = str(exc) if isinstance(exc, IdentityError) else "Cannot read or write local build identity inputs"
        print(f"Build identity failed: {message}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
