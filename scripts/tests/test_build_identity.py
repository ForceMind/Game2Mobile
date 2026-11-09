"""Synthetic identity/Mach-O tests; no game data, Apple build or signing.

The fixture below independently packs a minimal Mach-O container containing
recognizable test bytes. It is never executed and is not a valid game App.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts.build_identity import (
    IdentityError, MANIFEST, MODULES, PAGE, RUNTIME_FILES,
    create_identity, fingerprint, guest_sections, read_identity, source_state,
    verify_identity,
)

SOURCE = {"commit": "a" * 40, "dirty": False}
BUILD = "db0507f36b84200ac05f75d76ed5026f"
CHAIN = "012345abcdef"


def write_macho(path: Path, images: dict[str, bytes]) -> dict:
    """Independent serializer: three segments, six regular 16 KiB sections."""
    text = []
    writable = []
    for name, data in images.items():
        padded = data + bytes((-len(data)) % PAGE)
        text.extend([(f"__dm{name}x0", padded[:PAGE]),
                     (f"__dm{name}x1", padded[2 * PAGE:])])
        writable.append((f"__DM{name}W", [("__img", padded[PAGE:2 * PAGE])]))
    groups = [("__TEXT", text), *writable]
    command_size = sum(72 + 80 * len(rows) for _, rows in groups)
    data_start = PAGE
    commands, content, locations = [], bytearray(bytes(PAGE)), {}
    for segment, rows in groups:
        segment_start = 0 if segment == "__TEXT" else data_start
        segment_end = data_start + sum(len(data) for _, data in rows)
        prot = 5 if segment == "__TEXT" else 3
        command = bytearray(struct.pack("<II16sQQQQiiII", 0x19, 72 + 80 * len(rows),
            segment.encode(), 0x100000000 + segment_start, segment_end - segment_start,
            segment_start, segment_end - segment_start, prot, prot, len(rows), 0))
        for section, data in rows:
            command.extend(struct.pack("<16s16sQQ8I", section.encode(), segment.encode(),
                0x100000000 + data_start, len(data), data_start, 14, 0, 0, 0, 0, 0, 0))
            locations[(segment, section)] = (data_start, len(data))
            content.extend(data)
            data_start += len(data)
        commands.append(command)
    header = struct.pack("<8I", 0xFEEDFACF, 0x0100000C, 0, 2, len(groups), command_size, 0, 0)
    content[:len(header)] = header
    content[32:32 + command_size] = b"".join(commands)
    path.write_bytes(content)
    return locations


class BuildIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo, self.out, self.app = (self.base / p for p in ("source", "module outputs", "DmIOS.app"))
        for directory in (self.repo / "dm/gfx/nvn", self.repo / "dm/tools", self.out, self.app / "dm"):
            directory.mkdir(parents=True)
        (self.repo / "dm/PRODUCT").write_text("3.3.94012-r44\n")
        (self.repo / "dm/gfx/nvn/dmsh_chain.h").write_text(f'#define DMSH_CHAIN "{CHAIN}"\n')
        rewriter = self.repo / "dm/tools/patch_nso.py"
        rewriter.write_text(f"# INERT fixture, never executed\nRULE_BUILD = '{BUILD}'\n")
        sha = hashlib.sha256(rewriter.read_bytes()).hexdigest()
        for marker in ("build_src.sha256", "product.complete.sha256"):
            (self.out / marker).write_text(sha + "\n")
        self.images = {}
        for name in MODULES:
            # Different bytes per module and segment; the last page needs padding.
            data = (name.encode() * (PAGE * 3))[:PAGE * 2 + 123]
            self.images[name] = data
            (self.out / f"{name}.patched.bin").write_bytes(data)
            (self.out / f"{name}.fixups.tsv").write_text(
                "# TEXT_END\t0x4000\n# KEY_PAGE_OFF\t0x4000\n"
                "# KEY_PAGE_SIZE\t0x4000\n# PATCH_OFF\t0x8000\n")
            (self.out / f"{name}.gates.tsv").write_text("")  # Empty gates are legal.
            (self.out / f"{name}.cuts.tsv").write_text(f"# BUILD_ID\t{BUILD}\n")
            for suffix in ("fixups.tsv", "gates.tsv", "cuts.tsv"):
                shutil.copy2(self.out / f"{name}.{suffix}", self.app / f"dm/{name}.{suffix}")
        for name in ("shader_map.tsv", "pso_manifest.tsv", "c1_full.tsv"):
            path = self.repo / "dm/gfx/nvn" / name
            path.write_text(f"INERT {name}; no game data\n")
            shutil.copy2(path, self.app / "dm" / name)
        self.shaders = self.app / "msl" / ("b-" + CHAIN)
        self.shaders.mkdir(parents=True)
        (self.shaders / ("0" * 16 + "_b.metallib")).write_bytes(b"INERT shader bytes")
        (self.shaders / ("0" * 16 + "_b.json")).write_text('{"fixture":true}\n')
        patcher = mock.patch("scripts.build_identity.source_state", return_value=SOURCE.copy())
        self.source = patcher.start()
        self.addCleanup(patcher.stop)
        self.manifest = create_identity(self.repo, self.out, self.app, "metal4")
        self.save()
        self.locations = write_macho(self.app / "DmIOS", self.images)

    def save(self):
        self.manifest["fingerprint"] = fingerprint(self.manifest)
        (self.app / MANIFEST).write_text(json.dumps(self.manifest))

    def verify(self, **options):
        return verify_identity(self.app, "metal4", repo=self.repo, **options)

    def test_roundtrip_binds_six_actual_sections_and_shader_bytes(self):
        self.assertEqual(guest_sections(self.app / "DmIOS"), self.locations)
        result = self.verify(require_clean=True, expected_commit=SOURCE["commit"])
        self.assertTrue(result["embedded_guest_bytes_verified"])
        self.assertTrue(result["bundled_shader_bytes_verified"])
        self.assertTrue(result["build_identity_source_clean"])
        self.assertEqual(result["build_identity_fingerprint"], self.manifest["fingerprint"])
        serialized = json.dumps(self.manifest)
        self.assertNotIn(str(self.base), serialized)
        self.assertNotIn("INERT shader bytes", serialized)
        self.assertEqual(self.manifest, create_identity(self.repo, self.out, self.app, "metal4"))

    def test_embedded_byte_tamper_fails_even_with_valid_manifest(self):
        path = self.app / "DmIOS"
        content = bytearray(path.read_bytes())
        offset, _ = self.locations[("__TEXT", "__dmmainx0")]
        content[offset + 100] ^= 1
        path.write_bytes(content)
        with self.assertRaisesRegex(IdentityError, "section hash mismatch"):
            self.verify()

    def test_embed_zero_padding_is_hashed(self):
        path = self.app / "DmIOS"
        content = bytearray(path.read_bytes())
        offset, size = self.locations[("__TEXT", "__dmsdkx1")]
        content[offset + size - 1] = 7
        path.write_bytes(content)
        with self.assertRaisesRegex(IdentityError, "section hash mismatch"):
            self.verify()

    def test_each_runtime_table_is_bound(self):
        for relative in RUNTIME_FILES:
            with self.subTest(relative=relative):
                path = self.app / relative
                before = path.read_bytes()
                path.write_bytes(before + b"mismatch")
                with self.assertRaisesRegex(IdentityError, "runtime file hash mismatch"):
                    self.verify()
                path.write_bytes(before)

    def test_shader_content_changed_after_copy_is_rejected(self):
        next(self.shaders.glob("*.metallib")).write_bytes(b"DIFFERENT shader fixture")
        with self.assertRaisesRegex(IdentityError, "shader cache hash mismatch"):
            self.verify()

    def test_finder_metadata_matches_xcode_folder_copy_exclusion(self):
        metadata = self.shaders / ".DS_Store"
        metadata.write_bytes(b"INERT Finder metadata")
        created = create_identity(self.repo, self.out, self.app, "metal4")
        self.assertEqual(created, self.manifest)
        metadata.unlink()  # Xcode strips this file while copying folder resources.
        self.assertTrue(self.verify()["bundled_shader_bytes_verified"])

    def test_shader_cache_extra_or_missing_file_rejected(self):
        extra = self.shaders / "stale.metallib"
        extra.write_bytes(b"stale")
        with self.assertRaisesRegex(IdentityError, "shader cache hash mismatch"):
            self.verify()
        extra.unlink()
        next(self.shaders.glob("*.json")).unlink()
        with self.assertRaisesRegex(IdentityError, "shader cache hash mismatch"):
            self.verify()

    def test_wrong_profile_and_source_cannot_pass(self):
        with self.assertRaisesRegex(IdentityError, "profile mismatch"):
            verify_identity(self.app, "m3", repo=self.repo)
        self.source.return_value = {**SOURCE, "commit": "b" * 40}
        with self.assertRaisesRegex(IdentityError, "source commit"):
            self.verify()
        with self.assertRaisesRegex(IdentityError, "Source commit changed"):
            self.verify(expected_commit=SOURCE["commit"])

    def test_dirty_source_is_explicit_and_m1_rejects_it(self):
        self.source.return_value = {**SOURCE, "dirty": True}
        self.manifest = create_identity(self.repo, self.out, self.app, "metal4")
        self.save()
        self.assertFalse(self.verify()["build_identity_source_clean"])
        with self.assertRaisesRegex(IdentityError, "clean-state"):
            self.verify(require_clean=True)

    def test_product_or_chain_change_fails(self):
        (self.repo / "dm/PRODUCT").write_text("other-version\n")
        with self.assertRaisesRegex(IdentityError, "product, rewriter or shader chain"):
            self.verify()

    def test_stale_or_incomplete_module_build_rejected(self):
        marker = self.out / "product.complete.sha256"
        old = marker.read_text()
        marker.write_text("0" * 64)
        with self.assertRaisesRegex(IdentityError, "different rewriter"):
            create_identity(self.repo, self.out, self.app, "metal4")
        marker.write_text(old)
        (self.out / ".product-building").write_text("in progress\n")
        with self.assertRaisesRegex(IdentityError, "still in progress"):
            create_identity(self.repo, self.out, self.app, "metal4")

    def test_staged_module_and_shader_mixups_rejected_before_build(self):
        path = self.app / "dm/sdk.fixups.tsv"
        path.write_text("different")
        with self.assertRaisesRegex(IdentityError, "differs from its image"):
            create_identity(self.repo, self.out, self.app, "metal4")
        shutil.copy2(self.out / "sdk.fixups.tsv", path)
        (self.app / "dm/c1_full.tsv").write_text("stale tracked table")
        with self.assertRaisesRegex(IdentityError, "differ from tracked"):
            create_identity(self.repo, self.out, self.app, "metal4")

    def test_wrong_game_build_id_rejected(self):
        for path in (self.out / "main.cuts.tsv", self.app / "dm/main.cuts.tsv"):
            path.write_text("# BUILD_ID\t" + "b" * 32 + "\n")
        with self.assertRaisesRegex(IdentityError, "pinned rewriter"):
            create_identity(self.repo, self.out, self.app, "metal4")

    def test_bad_layout_rejected(self):
        for text in ("# TEXT_END\t0\n", "# TEXT_END\t0x4000\n# TEXT_END\t0x4000\n",
                     "# TEXT_END\tnope\n"):
            (self.out / "main.fixups.tsv").write_text(text)
            with self.assertRaises(IdentityError):
                create_identity(self.repo, self.out, self.app, "metal4")

    def test_optional_bootlist_is_bound_if_present(self):
        path = self.app / "dm/bootlist.tsv"
        path.write_text("INERT optional list\n")
        with self.assertRaisesRegex(IdentityError, "Unexpected optional"):
            self.verify()
        self.manifest = create_identity(self.repo, self.out, self.app, "metal4")
        self.save()
        self.assertTrue(self.verify()["build_identity_verified"])
        path.unlink()
        with self.assertRaisesRegex(IdentityError, "Missing or empty"):
            self.verify()

    def test_symlinked_resource_directory_is_rejected(self):
        original = self.app / "dm"
        moved = self.base / "external tables"
        original.rename(moved)
        original.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(IdentityError, "Symlinked"):
            self.verify()

    def test_symlinked_shader_file_is_rejected(self):
        path = next(self.shaders.glob("*.metallib"))
        moved = self.base / "external.metallib"
        path.rename(moved)
        path.symlink_to(moved)
        with self.assertRaisesRegex(IdentityError, "Symlinked"):
            self.verify()

    def test_manifest_missing_corrupt_duplicate_or_oversized_fails(self):
        path = self.app / MANIFEST
        for contents in ("{}", "{", '{"schema":1,"schema":2}', " " * 131073,
                         '{"nested":' + '[' * 10000 + '0' + ']' * 10000 + '}'):
            path.write_text(contents)
            with self.assertRaises(IdentityError):
                read_identity(self.app)
        path.unlink()
        with self.assertRaises(IdentityError):
            read_identity(self.app)

    def test_manifest_paths_cannot_escape_app(self):
        self.manifest["runtime_files"]["../../private.txt"] = {"size": 1, "sha256": "a" * 64}
        self.save()
        with self.assertRaisesRegex(IdentityError, "runtime file inventory"):
            self.verify()

    def test_missing_duplicate_or_wrong_section_record_rejected(self):
        baseline = copy.deepcopy(self.manifest)
        for change in ("missing", "duplicate", "wrong-name"):
            self.manifest = copy.deepcopy(baseline)
            sections = self.manifest["modules"]["main"]["sections"]
            if change == "missing":
                sections.pop()
            elif change == "duplicate":
                sections[1] = sections[0]
            else:
                sections[0]["section"] = "__notmain"
            self.save()
            with self.assertRaises(IdentityError):
                self.verify()

    def test_recorded_whole_image_size_and_hash_are_actually_checked(self):
        self.manifest["modules"]["main"]["image_size"] = 1
        self.save()
        with self.assertRaisesRegex(IdentityError, "image size"):
            self.verify()
        self.manifest["modules"]["main"]["image_size"] = len(self.images["main"])
        self.manifest["modules"]["main"]["image_sha256"] = "0" * 64
        self.save()
        with self.assertRaisesRegex(IdentityError, "image hash mismatch"):
            self.verify()

    def test_macho_truncation_wrong_cpu_and_load_bounds_fail(self):
        path = self.app / "DmIOS"
        baseline = path.read_bytes()
        bad_cpu = bytearray(baseline)
        struct.pack_into("<I", bad_cpu, 4, 7)
        bad_count = bytearray(baseline)
        struct.pack_into("<I", bad_count, 16, 0xFFFFFFFF)
        bad_length = bytearray(baseline)
        struct.pack_into("<I", bad_length, 36, 0x10000000)
        for value in (b"not a Mach-O", baseline[:1000], bad_cpu, bad_count, bad_length):
            path.write_bytes(value)
            with self.assertRaises(IdentityError):
                self.verify()

    def test_guest_section_zero_fill_wrong_permissions_or_duplicate_fail(self):
        path = self.app / "DmIOS"
        baseline = path.read_bytes()
        for change in ("zero-fill", "permissions", "duplicate", "outside-segment"):
            changed = bytearray(baseline)
            first = 32 + 72
            if change == "zero-fill":
                struct.pack_into("<I", changed, first + 64, 1)
            elif change == "permissions":
                struct.pack_into("<i", changed, 32 + 60, 7)
            elif change == "duplicate":
                changed[first + 80:first + 96] = changed[first:first + 16]
            else:
                struct.pack_into("<I", changed, first + 48, len(changed) - 1)
            path.write_bytes(changed)
            with self.assertRaises(IdentityError):
                self.verify()

    def test_cli_failure_does_not_echo_private_paths(self):
        script = Path(__file__).resolve().parents[1] / "build_identity.py"
        private = self.base / "SECRET_owner_path"
        result = subprocess.run([sys.executable, str(script), "verify", "--profile", "metal4",
                                 "--app", str(private)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("SECRET_owner_path", result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)


class SourceStateTests(unittest.TestCase):
    def test_git_source_state_tracks_commit_and_tracked_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def git(*args):
                return subprocess.run(["git", *args], cwd=root, check=True, text=True,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            git("init", "-q")
            (root / "fixture.txt").write_text("INERT source state fixture\n")
            shutil.copy2(Path(__file__).resolve().parents[2] / ".gitignore", root / ".gitignore")
            git("add", "fixture.txt", ".gitignore")
            git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
            clean = source_state(root)
            self.assertEqual(len(clean["commit"]), 40)
            self.assertFalse(clean["dirty"])
            cache = root / "scripts/__pycache__/fixture.cpython-312.pyc"
            cache.parent.mkdir(parents=True)
            cache.write_bytes(b"INERT generated cache")
            self.assertEqual(source_state(root), clean)
            (root / "fixture.txt").write_text("changed\n")
            self.assertEqual(source_state(root), {**clean, "dirty": True})
            git("checkout", "--", "fixture.txt")
            (root / "new-source.c").write_text("/* new untracked source */\n")
            self.assertEqual(source_state(root), {**clean, "dirty": True})


if __name__ == "__main__":
    unittest.main()
