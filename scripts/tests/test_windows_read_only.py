"""Windows control-plane invariants without requiring Windows or private input."""
import unittest
from unittest.mock import patch

from scripts import g2mctl


class WindowsReadOnlyTests(unittest.TestCase):
    def test_windows_capabilities_exclude_local_ios_build(self):
        with patch.object(g2mctl.sys, 'platform', 'win32'):
            result = g2mctl.operate(['capabilities'])
        self.assertFalse(result['operations']['build-local-explicit'])
        self.assertTrue(result['operations']['status'])
        self.assertEqual(result['exit_code'], 0)

    def test_windows_explicit_build_does_not_import_or_open_private_workspace(self):
        with patch.object(g2mctl.sys, 'platform', 'win32'):
            result = g2mctl.operate(['build', '--execute-local',
                                     '--workspace', 'C:/secret/game-files', '--stage', 'all'])
        self.assertEqual(result['code'], 'NOT_SUPPORTED')
        self.assertEqual(result['exit_code'], 3)
        self.assertFalse(result['ok'])
        self.assertEqual(result['scope'], 'local-read-only')
        self.assertNotIn('C:/secret', str(result))

    def test_windows_implicit_build_also_refused(self):
        with patch.object(g2mctl.sys, 'platform', 'win32'):
            result = g2mctl.operate(['build'])
        self.assertEqual(result['code'], 'NOT_SUPPORTED')
        self.assertEqual(result['exit_code'], 3)


if __name__ == '__main__':
    unittest.main()
