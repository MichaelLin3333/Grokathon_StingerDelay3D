import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import upstream


class UpstreamTests(unittest.TestCase):
    def setUp(self):
        self.previous = upstream.status()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'docs').mkdir()
        self.root_patch = patch.object(upstream, 'ROOT', self.root)
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.temp.cleanup()
        with upstream._LOCK:
            upstream._STATE.clear()
            upstream._STATE.update(self.previous)

    def test_remote_check_survives_local_git_failure(self):
        commits = [{'sha': 'a' * 40, 'message': 'Shared contracts updated'}]
        with patch.object(upstream, '_git', side_effect=OSError('local checkout unavailable')), \
             patch.object(upstream, '_fetch_commits', return_value=commits):
            result = upstream.check()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['remote_sha'], 'a' * 40)
        self.assertEqual(result['transport'], 'github_api')

    def test_git_transport_fallback_does_not_present_old_commit_details(self):
        with upstream._LOCK:
            upstream._STATE.update(remote_sha='b' * 40, commits=[{'sha': 'b' * 40}])
        def git(*args, **kwargs):
            return 'c' * 40 if args[0] == 'rev-parse' else 'd' * 40 + '\tHEAD'
        with patch.object(upstream, '_git', side_effect=git), \
             patch.object(upstream, '_fetch_commits', side_effect=OSError('API unavailable')):
            result = upstream.check()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['remote_sha'], 'd' * 40)
        self.assertEqual(result['commits'], [])
        self.assertTrue(result['commit_details_stale'])


if __name__ == '__main__':
    unittest.main()
