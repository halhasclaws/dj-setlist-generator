"""Exercise discovery orchestration without provider or database side effects."""
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch
from worker.jobs import discover_artist as job
from config import Config

class _JobTestBase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.mocks = {}
        for name in ['fetch_one', 'execute', 'insert_worker_event', 'mark_submission',
                     'finalize_submission_from_runs', '_dispatch_pending', 'ArtistManager',
                     'DjSetDiscoverer', 'resolve_canonical_source_url', 'json_value', 'fetch_all']:
            self.mocks[name] = self.stack.enter_context(patch.object(job, name))
        self.mocks['resolve_canonical_source_url'].side_effect = lambda url: url
        self.mocks['json_value'].side_effect = lambda value: value
        self.mocks['fetch_all'].return_value = []
        self.stack.enter_context(patch.object(Config, 'DISCOVERY_AI_REVIEW', 'off'))
        self.mocks['fetch_one'].side_effect = [
            {'id': 'submission', 'artist_name': 'Test DJ', 'artist_aliases': ['Alias'], 'max_sets_override': 1},
            {'count': 1},
        ]
        self.original_limit = Config.MAX_SETS_PER_ARTIST


class DiscoveryJobTests(_JobTestBase):
    def test_discovery_queues_then_dispatches_and_restores_limit(self):
        candidate = SimpleNamespace(url='https://soundcloud.com/test/set', platform='soundcloud',
            title='Test set', duration_minutes=30, event=None, year=None, source_links=[])
        def discover():
            self.assertEqual(Config.MAX_SETS_PER_ARTIST, 1)
            return [candidate]
        self.mocks['DjSetDiscoverer'].return_value.discover.side_effect = discover
        job.run('submission')
        statements = [call.args[0] for call in self.mocks['execute'].call_args_list]
        self.assertTrue(any('insert into ops.set_runs' in sql and 'not exists' in sql for sql in statements))
        self.mocks['_dispatch_pending'].assert_called_once()
        self.assertEqual(Config.MAX_SETS_PER_ARTIST, self.original_limit)

    def test_empty_discovery_fails_without_dispatch(self):
        self.mocks['DjSetDiscoverer'].return_value.discover.return_value = []
        job.run('submission')
        self.mocks['mark_submission'].assert_called_with('submission', status='failed', error_summary='No DJ sets discovered')
        self.mocks['_dispatch_pending'].assert_not_called()
        self.assertEqual(Config.MAX_SETS_PER_ARTIST, self.original_limit)

    def test_provider_failure_records_failure_and_restores_limit(self):
        self.mocks['DjSetDiscoverer'].return_value.discover.side_effect = RuntimeError('provider unavailable')
        with self.assertRaisesRegex(RuntimeError, 'provider unavailable'):
            job.run('submission')
        self.mocks['mark_submission'].assert_called_with('submission', status='failed', error_summary='provider unavailable')
        self.mocks['_dispatch_pending'].assert_not_called()
        self.assertEqual(Config.MAX_SETS_PER_ARTIST, self.original_limit)

    def test_already_published_discovery_finishes_without_new_dispatch(self):
        self.mocks['fetch_one'].side_effect = [
            {'id':'submission','artist_name':'Test DJ','artist_aliases':[],'max_sets_override':1}, {'count':0}]
        self.mocks['DjSetDiscoverer'].return_value.discover.return_value = [SimpleNamespace(
            url='https://soundcloud.com/test/set', platform='soundcloud', title='Test set',
            duration_minutes=30, event=None, year=None, source_links=[])]
        job.run('submission')
        self.mocks['finalize_submission_from_runs'].assert_called_once_with('submission')
        self.mocks['_dispatch_pending'].assert_not_called()


def _set(url, title='Test set'):
    return SimpleNamespace(url=url, platform='soundcloud', title=title, duration_minutes=60,
                           event='Test DJ', year='2024', source_links=[])


class DiscoveryFilterTests(_JobTestBase):
    """Skip list and AI review, with the database and the claude CLI stubbed."""

    def queued_urls(self):
        return [call.args[1][0] for call in self.mocks['execute'].call_args_list
                if 'insert into ops.set_runs' in call.args[0]]

    def dropped(self):
        return [(call.args[1][1], call.args[1][5], call.args[1][6]) for call in self.mocks['execute'].call_args_list
                if 'rejection_reason' in call.args[0]]

    def test_previously_cancelled_source_is_skipped(self):
        self.mocks['fetch_all'].return_value = [
            {'source_url': 'https://soundcloud.com/x/wrong', 'status': 'cancelled', 'set_title': 'Wrong', 'source_metadata': {}},
            {'source_url': 'https://soundcloud.com/x/retried', 'status': 'cancelled', 'set_title': 'R', 'source_metadata': {}},
            {'source_url': 'https://soundcloud.com/x/retried', 'status': 'completed', 'set_title': 'R', 'source_metadata': {}},
        ]
        self.mocks['DjSetDiscoverer'].return_value.discover.return_value = [
            _set('https://soundcloud.com/x/wrong'), _set('https://soundcloud.com/x/new'), _set('https://soundcloud.com/x/retried')]
        job.run('submission')
        self.assertEqual(['https://soundcloud.com/x/new', 'https://soundcloud.com/x/retried'], self.queued_urls())
        self.assertEqual([('https://soundcloud.com/x/wrong', 'skipped', 'cancelled in an earlier discovery')], self.dropped())

    def test_ai_review_rejects_but_queues_unsure(self):
        Verdict = job.discovery_review.Verdict
        self.mocks['DjSetDiscoverer'].return_value.discover.return_value = [
            _set('https://soundcloud.com/x/a'), _set('https://soundcloud.com/x/b'), _set('https://soundcloud.com/x/c')]
        with patch.object(Config, 'DISCOVERY_AI_REVIEW', 'auto'), \
             patch.object(job.discovery_review, 'available', return_value=True), \
             patch.object(job.discovery_review, 'build_profile', return_value={'profile': 'p', 'namesakes': []}) as profile, \
             patch.object(job.discovery_review, 'review', return_value=[
                 Verdict('keep', 'set', 'ok'), Verdict('reject', 'namesake', 'folk singer'), Verdict('unsure', 'other', '?')]):
            job.run('submission')
        self.assertTrue(profile.call_args.kwargs['web'])  # no accepted sets yet, so the profile uses the web
        self.assertEqual(['https://soundcloud.com/x/a', 'https://soundcloud.com/x/c'], self.queued_urls())
        self.assertEqual([('https://soundcloud.com/x/b', 'rejected', 'AI review: namesake: folk singer')], self.dropped())

    def test_ai_review_failure_queues_everything(self):
        self.mocks['DjSetDiscoverer'].return_value.discover.return_value = [
            _set('https://soundcloud.com/x/a'), _set('https://soundcloud.com/x/b')]
        with patch.object(Config, 'DISCOVERY_AI_REVIEW', 'auto'), \
             patch.object(job.discovery_review, 'available', return_value=True), \
             patch.object(job.discovery_review, 'build_profile', side_effect=RuntimeError('CLI not logged in')):
            job.run('submission')
        self.assertEqual(['https://soundcloud.com/x/a', 'https://soundcloud.com/x/b'], self.queued_urls())
        events = [call.kwargs.get('event_type') for call in self.mocks['insert_worker_event'].call_args_list]
        self.assertIn('submission.discovery.review_failed', events)

    def test_missing_cli_skips_review(self):
        self.mocks['DjSetDiscoverer'].return_value.discover.return_value = [_set('https://soundcloud.com/x/a')]
        with patch.object(Config, 'DISCOVERY_AI_REVIEW', 'auto'), \
             patch.object(job.discovery_review, 'available', return_value=False), \
             patch.object(job.discovery_review, 'review') as review:
            job.run('submission')
        review.assert_not_called()
        self.assertEqual(['https://soundcloud.com/x/a'], self.queued_urls())
