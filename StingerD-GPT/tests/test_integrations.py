import datetime as dt
import os
import unittest
import tempfile
from pathlib import Path
import tempfile
from pathlib import Path
import copy
from unittest.mock import patch

from server import integrations as api
from server import upstream


class PlannerStub:
    def __init__(self):
        self.calls = []
        self.trace = {'id': 'trusted', 'constraints': {'origin': 'student-center', 'destination': 'klaus'},
            'origin': {'id': 'student-center', 'name': 'Student Center'},
            'destination': {'id': 'klaus', 'name': 'Klaus'},
            'chosen': {'label': 'Walk', 'duration_minutes': 12.4, 'social_applied': False},
            'allowed_numbers': ['12.4'], 'explanation_facts': ['Walk to Klaus in 12.4 minutes.']}

    def places(self):
        return [{'id': ident, 'name': name} for ident, name in [
            ('student-center', 'Student Center'), ('klaus', 'Klaus Advanced Computing'),
            ('clough', 'Clough'), ('kendeda', 'Kendeda')]]

    def plan_trip(self, body):
        self.calls.append(body)
        return self.trace

    def verify_trace(self, trace):
        return trace is self.trace

    def day_schedule(self, body, events):
        return {'items': [{'event': event, 'trace': self.trace} for event in events if event['place_id']],
                'unresolved': [event for event in events if not event['place_id']]}


class IntegrationsTests(unittest.TestCase):
    def setUp(self):
        self.planner = PlannerStub()
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        api._TOKEN.clear()
        api._OAUTH_STATES.clear()

    def tearDown(self):
        self.env.stop()

    def dispatch(self, method, path, body=None, query=None):
        return api.dispatch(method, path, body or {}, query or {}, self.planner)

    def test_status_is_honest_without_keys(self):
        status = api.integration_status()
        self.assertEqual(status['grok']['mode'], 'template')
        self.assertEqual(status['calendar']['mode'], 'demo')
        self.assertFalse(status['x']['configured'])
        self.assertEqual(status['voice']['mode'], 'browser')

    def test_demo_calendar_and_schedule_work_offline(self):
        with patch.object(api, '_request_json', side_effect=AssertionError('No network')):
            _, cal, _ = self.dispatch('GET', '/calendar/events')
            self.assertEqual(cal['mode'], 'demo')
            self.assertEqual(len(cal['events']), 3)
            self.assertTrue(all(event['place_id'] for event in cal['events']))
            _, schedule, _ = self.dispatch('POST', '/schedule')
            self.assertEqual(len(schedule['items']), 3)
            _, upcoming, _ = self.dispatch('GET', '/calendar/next')
            self.assertIsNotNone(upcoming['event'])

    def test_import_rejects_naive_or_reversed_times(self):
        bad = {'title': 'Class', 'start': '2026-11-03T12:00:00', 'end': '2026-11-03T13:00:00'}
        with self.assertRaises(ValueError):
            api.validate_events([bad], self.planner)
        bad.update(start='2026-11-03T13:00:00-05:00', end='2026-11-03T12:00:00-05:00')
        with self.assertRaises(ValueError):
            api.validate_events([bad], self.planner)

    def test_unresolved_calendar_location_remains_unresolved(self):
        item = {'title': 'Remote Event', 'start': '2026-11-03T12:00:00-05:00',
                'end': '2026-11-03T13:00:00-05:00', 'location': 'Unknown Building, elsewhere'}
        event = api.validate_events([item], self.planner)[0]
        self.assertIsNone(event['place_id'])

    def test_helper_reconstructs_untrusted_browser_trace(self):
        body = {'message': 'Explain this route', 'trace': {**self.planner.trace,
                'allowed_numbers': ['999'], 'explanation_facts': ['Arrive in 999 minutes.']}}
        result = api.chat(body, self.planner)
        self.assertNotIn('999', result['reply'])
        self.assertEqual(result['provider'], 'template')
        self.assertTrue(result['verified'])
        self.assertGreater(len(self.planner.calls), 0)

    def test_numeric_hallucination_rejected(self):
        self.assertTrue(api.verify_text('Walk for 12.4 minutes.', self.planner.trace))
        self.assertFalse(api.verify_text('It will take 999 minutes.', self.planner.trace))
        with patch.dict(os.environ, {'XAI_API_KEY': 'not-a-real-key'}), \
             patch.object(api, '_live_reply', return_value='Take 999 minutes.'):
            result = api.chat({'message': 'Explain the route', 'trace': self.planner.trace}, self.planner)
        self.assertEqual(result['provider'], 'template')
        self.assertIn('verification', result['warning'])
        self.assertNotIn('999', result['reply'])

    def test_calendar_intent_invokes_arrive_by(self):
        result = api.chat({'message': 'When should I leave for my next calendar event?'}, self.planner)
        self.assertTrue(result['verified'])
        self.assertIn('arrive_by', self.planner.calls[-1])

    def test_imported_next_class_uses_supplied_origin(self):
        start = api._now() + dt.timedelta(hours=2)
        event = {'id': 'local', 'title': 'My local class', 'location': 'Kendeda',
                 'place_id': 'kendeda', 'start': start.isoformat(),
                 'end': (start + dt.timedelta(hours=1)).isoformat()}
        with patch.object(api, 'calendar_events', side_effect=AssertionError('Imported events should be used')):
            result = api.chat({'message': 'When should I leave for my next class?',
                               'origin': 'clough', 'events': [event]}, self.planner)
        self.assertEqual(self.planner.calls[-1]['origin'], 'clough')
        self.assertEqual(self.planner.calls[-1]['destination'], 'kendeda')
        self.assertEqual(result['calendar_mode'], 'imported')
        self.assertIn('imported schedule', result['reply'])

    def test_empty_imported_events_do_not_fall_back_to_demo(self):
        with patch.object(api, 'calendar_events', side_effect=AssertionError('No demo fallback')):
            result = api.chat({'message': 'My next class?', 'events': []}, self.planner)
        self.assertNotIn('trace', result)
        self.assertEqual(result['calendar_mode'], 'imported')
        self.assertIn('no upcoming', result['reply'])

    def test_selected_alternative_is_taken_from_trusted_cache(self):
        from server import planner
        import copy
        trace = planner.plan_trip({'origin': 'student-center', 'destination': 'klaus',
                                   'depart_at': '2026-11-03T09:30:00-05:00'})
        self.assertTrue(trace['alternatives'])
        browser_trace = copy.deepcopy(trace)
        selected = copy.deepcopy(trace['alternatives'][0])
        browser_trace['chosen'] = copy.deepcopy(selected)
        browser_trace['chosen']['duration_minutes'] = 999
        browser_trace['allowed_numbers'] = ['999']
        result = api.chat({'message': 'Explain this route to Klaus', 'trace': browser_trace}, planner)
        self.assertEqual(result['trace']['chosen']['id'], selected['id'])
        self.assertEqual(result['trace']['chosen']['duration_minutes'], selected['duration_minutes'])
        self.assertNotIn('999', result['reply'])
        self.assertTrue(planner.verify_trace(result['trace']))
        self.assertEqual(planner.get_trace(trace['id'])['chosen']['id'], trace['chosen']['id'])

    def test_leave_now_assessment_uses_replay_time_and_existing_deadline(self):
        from server import planner
        trace = planner.plan_trip({'origin': 'student-center', 'destination': 'klaus',
                                   'arrive_by': '2026-11-03T10:00:00-05:00'})
        result = api.chat({'message': 'If I leave now, will I be fine?', 'trace': trace,
                           'replay_at': '2026-11-03T09:59:00-05:00'}, planner)
        self.assertEqual(result['trace']['chosen']['departure_time'], '2026-11-03T09:59:00-05:00')
        self.assertEqual(result['trace']['constraints']['arrive_by'], '2026-11-03T10:00:00-05:00')
        self.assertEqual(result['trace']['constraints']['evaluate_at'], '2026-11-03T09:59:00-05:00')
        self.assertLess(result['trace']['chosen']['p_on_time'], .9)
        self.assertIn('risk of arriving late', result['reply'])
        self.assertIn('on-time probability', result['reply'])
        self.assertTrue(result['verified'])

    def test_leave_now_assessment_can_find_imported_same_day_event(self):
        from server import planner
        event = {'id': 'local', 'title': 'Imported class', 'place_id': 'klaus', 'location': 'Klaus',
                 'start': '2026-11-03T10:00:00-05:00', 'end': '2026-11-03T11:00:00-05:00'}
        result = api.chat({'message': 'Will I make it?', 'events': [event],
                           'origin': 'student-center', 'replay_at': '2026-11-03T09:30:00-05:00'}, planner)
        self.assertEqual(result['calendar_mode'], 'imported')
        self.assertIn('likely to make it', result['reply'])
        self.assertIn('no guarantee', result['reply'])
        self.assertEqual(result['trace']['constraints']['evaluate_at'], '2026-11-03T09:30:00-05:00')

    def test_leave_now_never_silently_moves_to_next_day(self):
        start = '2026-11-04T10:00:00-05:00'
        event = {'title': 'Tomorrow class', 'location': 'Klaus', 'start': start,
                 'end': '2026-11-04T11:00:00-05:00'}
        result = api.chat({'message': 'Will I make it?', 'events': [event],
                           'replay_at': '2026-11-03T09:30:00-05:00'}, self.planner)
        self.assertNotIn('trace', result)
        self.assertIn('different date', result['reply'])
        self.assertEqual(self.planner.calls, [])

    def test_leave_now_requires_visible_replay_time(self):
        with self.assertRaises(ValueError):
            api.chat({'message': 'Will I make it?'}, self.planner)

    def test_live_reply_receives_trusted_selected_fields_and_no_geometry(self):
        from server import planner
        import copy
        import json
        trace = planner.plan_trip({'origin': 'student-center', 'destination': 'klaus',
                                   'depart_at': '2026-11-03T09:30:00-05:00'})
        browser_trace = copy.deepcopy(trace)
        selected = trace['alternatives'][0]
        browser_trace['chosen'] = {**selected, 'duration_minutes': 999}
        provider = {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'The selected route is ready.'}]}]}
        with patch.dict(os.environ, {'XAI_API_KEY': 'not-a-real-key'}), \
             patch.object(api, '_request_json', return_value=provider) as request:
            result = api.chat({'message': 'Explain this route', 'trace': browser_trace}, planner)
        self.assertEqual(result['provider'], 'grok')
        system = request.call_args.kwargs['data']['input'][0]['content']
        context = json.loads(system.split('\n', 1)[1])
        self.assertEqual(context['chosen']['id'], selected['id'])
        self.assertEqual(context['chosen']['duration_minutes'], selected['duration_minutes'])
        self.assertEqual(context['chosen']['quantiles'], selected['quantiles'])
        self.assertEqual(context['chosen']['departure_time'], selected['departure_time'])
        self.assertIn('p_on_time', context['chosen'])
        self.assertNotIn('geometry', context['chosen'])
        self.assertTrue(all('geometry' not in leg for leg in context['legs']))

    def test_unknown_selected_alternative_is_rejected(self):
        from server import planner
        import copy
        trace = planner.plan_trip({'origin': 'student-center', 'destination': 'klaus',
                                   'depart_at': '2026-11-03T09:30:00-05:00'})
        trace = copy.deepcopy(trace)
        trace['chosen']['id'] = 'not-a-server-choice'
        with self.assertRaises(ValueError):
            api.chat({'message': 'Explain this route', 'trace': trace}, planner)

    def test_place_time_intent(self):
        api.chat({'message': 'Plan a trip to Klaus by 8:30 pm, avoid stairs'}, self.planner)
        body = self.planner.calls[-1]
        self.assertEqual(body['destination'], 'klaus')
        self.assertTrue(body['avoid_stairs'])
        self.assertEqual(dt.datetime.fromisoformat(body['arrive_by']).hour, 20)

    def test_google_oauth_not_configured(self):
        code, result, headers = self.dispatch('GET', '/auth/google')
        self.assertEqual(code, 503)
        self.assertNotIn('Location', headers)

    def test_oauth_state_is_bound_to_browser_and_single_use(self):
        with patch.dict(os.environ, {'GOOGLE_CLIENT_ID': 'client', 'GOOGLE_CLIENT_SECRET': 'secret'}):
            code, _, headers = self.dispatch('GET', '/auth/google')
            self.assertEqual(code, 302)
            state = headers['Set-Cookie'].split('=', 1)[1].split(';', 1)[0]
            self.assertIn(state, api._OAUTH_STATES)
            code, _, _ = self.dispatch('GET', '/auth/google/callback', query={'state': [state], 'code': ['x'], '_oauth_cookie': 'wrong'})
            self.assertEqual(code, 400)
            self.assertNotIn(state, api._OAUTH_STATES)

    def test_google_failed_request_labels_demo_fallback(self):
        with patch.dict(os.environ, {'GOOGLE_CALENDAR_ACCESS_TOKEN': 'not-a-real-token'}), \
             patch.object(api, '_request_json', side_effect=OSError('network')):
            cal = api.calendar_events(self.planner)
        self.assertEqual(cal['mode'], 'demo')
        self.assertIn('warning', cal)

    def test_google_places_are_resolved_without_faking_unknowns(self):
        event = {'id': 'live', 'summary': 'Class', 'location': 'Unknown place',
                 'start': {'dateTime': '2026-11-03T12:00:00-05:00'},
                 'end': {'dateTime': '2026-11-03T13:00:00-05:00'}}
        with patch.dict(os.environ, {'GOOGLE_CALENDAR_ACCESS_TOKEN': 'not-a-real-token'}), \
             patch.object(api, '_request_json', return_value={'items': [event]}):
            cal = api.calendar_events(self.planner)
        self.assertEqual(cal['mode'], 'google')
        self.assertIsNone(cal['events'][0]['place_id'])

    def test_signals_are_explicitly_demonstration(self):
        _, payload, _ = self.dispatch('GET', '/signals/x')
        self.assertFalse(payload['live'])
        self.assertTrue(all(not signal['active'] for signal in payload['signals']))

    def test_upstream_network_failure_retains_last_revision(self):
        original = upstream.status()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'docs').mkdir()
                with upstream._LOCK:
                    upstream._STATE.update(remote_sha='last-known', last_success_at='earlier')
                with patch.object(upstream, 'ROOT', root), patch.object(upstream, '_git', side_effect=OSError('offline')), patch.object(upstream, '_fetch_commits', side_effect=OSError('offline')):
                    state = upstream.check()
                self.assertEqual(state['status'], 'error')
                self.assertEqual(state['remote_sha'], 'last-known')
                self.assertEqual(state['last_success_at'], 'earlier')
        finally:
            with upstream._LOCK:
                upstream._STATE.clear()
                upstream._STATE.update(original)


if __name__ == '__main__':
    unittest.main()
