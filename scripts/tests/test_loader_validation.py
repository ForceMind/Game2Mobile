"""Compile/run the actual portable metadata validator, without Apple/game files."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class LoaderValidationTests(unittest.TestCase):
    def test_real_header_with_synthetic_module_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'loader-check'
            subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-O2', '-Wall',
                            '-Wextra', '-Werror', str(ROOT / 'dm/host/tests/t_loader_validate.c'),
                            '-o', str(binary)], check=True, timeout=30)
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('5000 bounded mutations passed', run.stdout)

    def test_dirty_failures_with_monotonic_clock_shim_on_linux(self):
        # Linux runs the same C state machine with a test-only Mach clock shim.
        # Apple CI separately tests actual mach time and mprotect on macOS.
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            flags = []
            if sys.platform != 'darwin':
                (tmp / 'mach').mkdir()
                (tmp / 'mach/mach_time.h').write_text(
                    '#include <stdint.h>\n#include <time.h>\n'
                    'typedef struct { uint32_t numer, denom; } mach_timebase_info_data_t;\n'
                    'static int mach_timebase_info(mach_timebase_info_data_t *p) '
                    '{ p->numer=1; p->denom=1; return 0; }\n'
                    'static uint64_t mach_absolute_time(void) { struct timespec t; '
                    'clock_gettime(CLOCK_MONOTONIC, &t); return (uint64_t)t.tv_sec*1000000000+t.tv_nsec; }\n')
                flags = ['-I', str(tmp)]
            binary = tmp / 'dirty-check'
            subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-O1', '-pthread',
                            *flags, str(ROOT / 'dm/gfx/tests/t_dirty_failures.c'), '-o', str(binary)],
                           check=True, timeout=30)
            subprocess.run([str(binary)], check=True, timeout=15)

    def test_real_loader_calls_validators_before_table_walk_or_key_write(self):
        source = (ROOT / 'dm/host/loader.c').read_text()
        dynamic = source[source.index('static void parse_dynamic'):source.index('static void *module_sym_linear')]
        self.assertLess(dynamic.index('g2m_dynamic_validate(m)'), dynamic.index('build_symhash(m)'))
        layout = source[source.index('static void read_layout'):source.index('static void install_key_page')]
        self.assertIn('g2m_layout_line(m, line, &seen)', layout)
        self.assertIn('g2m_layout_validate(m, seen)', layout)
        self.assertNotIn("strrchr(line, '\\t') + 1", layout)

if __name__ == '__main__':
    unittest.main()
