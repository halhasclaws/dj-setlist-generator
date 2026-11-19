import unittest
from types import SimpleNamespace
from unittest import mock

import requests

from worker.jobs import process_set


class _Response:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.ok = 200 <= status < 300

    def json(self):
        return self._body

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(str(self.status_code))


class PublishReplayTest(unittest.TestCase):
    def _settings(self):
        return SimpleNamespace(api_base_url='https://app.test', internal_secret='x')

    def test_timeout_is_replayed_and_returns_committed_publication(self):
        calls = [requests.exceptions.ReadTimeout(), _Response(200, {'setId': 's1', 'slug': 'a'})]

        def fake(*_args, **_kwargs):
            item = calls.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with mock.patch.object(process_set, 'get_settings', self._settings), \
                mock.patch.object(process_set, 'post_callback', side_effect=fake) as post:
            out = process_set._publish_set_run_payload(set_run_id='r1', payload={})
        self.assertEqual(out['setId'], 's1')
        self.assertEqual(post.call_count, 2)

    def test_in_progress_waits_then_replays(self):
        calls = [_Response(409, {'errorCode': 'publication_in_progress'}), _Response(200, {'setId': 's1'})]
        with mock.patch.object(process_set, 'get_settings', self._settings), \
                mock.patch.object(process_set, 'post_callback', side_effect=lambda *a, **k: calls.pop(0)), \
                mock.patch('time.sleep') as sleep:
            out = process_set._publish_set_run_payload(set_run_id='r1', payload={})
        self.assertEqual(out['setId'], 's1')
        sleep.assert_called_once()


if __name__ == '__main__':
    unittest.main()
