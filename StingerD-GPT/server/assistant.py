"""Bounded in-memory conversational constraints and navigation actions.

The planner still owns all numeric outputs. No user message or calendar text is
written to disk; state expires after inactivity.
"""
import copy
import datetime as dt
import re
import threading
import time
from zoneinfo import ZoneInfo

TZ = ZoneInfo('America/New_York')
_LOCK = threading.RLock()
_STATES = {}


def _reference(body, trace=None):
    value = body.get('replay_at') or body.get('now') or (trace or {}).get('chosen', {}).get('departure_time')
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(TZ) if value else dt.datetime.now(TZ)


def _resolve(query, planner):
    query = re.sub(r'^(?:the|a)\s+', '', query.strip(), flags=re.I).strip(' .?,')
    try:
        return planner.resolve_place(query), None
    except ValueError:
        pass
    candidates = planner.search_places(query, 4)
    if candidates:
        first = candidates[0]
        if first['score'] >= .8 and (len(candidates) == 1 or first['score']-candidates[1]['score'] >= .04):
            return planner.resolve_place(first['id']), None
    return None, {'question': f'Which campus place do you mean by “{query}”?', 'options': [p['name'] for p in candidates[:3]]}


def _clock(text, reference):
    match = re.search(r'\b(?:by|before|at|make it|change (?:it|the time) to)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b', text, re.I)
    if not match:
        relative = re.search(r'\bin\s+(\d{1,3})\s+minutes?\b', text, re.I)
        return reference + dt.timedelta(minutes=int(relative[1])) if relative else None
    hour, minute, period = int(match[1]), int(match[2] or 0), (match[3] or '').lower()
    if minute >= 60 or hour > 23 or (period and not 1 <= hour <= 12):
        raise ValueError('Please provide a valid clock time.')
    if period:
        hour = hour % 12 + (12 if period == 'pm' else 0)
    day = reference.date()+dt.timedelta(days=1 if 'tomorrow' in text.lower() else 0)
    return dt.datetime.combine(day, dt.time(hour, minute), TZ)


def _constraints(trace):
    constraints = copy.deepcopy(trace.get('constraints') or {})
    constraints['origin'] = trace['origin']
    constraints['destination'] = trace['destination']
    if constraints.get('arrive_by'):
        constraints.pop('depart_at', None)
    return constraints


def converse(body, planner):
    from server import integrations as api
    message = body.get('message')
    if not isinstance(message, str) or not 0 < len(message.strip()) <= 2000:
        raise ValueError('Provide a message between one and two thousand characters.')
    cid = body.get('conversation_id')
    if not isinstance(cid, str) or not re.fullmatch(r'[\w-]{1,100}', cid):
        raise ValueError('conversation_id must contain letters, digits, underscores or hyphens.')
    with _LOCK:
        now = time.monotonic()
        for key in list(_STATES):
            if now-_STATES[key]['updated'] > 1800:
                del _STATES[key]
        if len(_STATES) >= 128 and cid not in _STATES:
            del _STATES[min(_STATES, key=lambda key: _STATES[key]['updated'])]
        state = copy.deepcopy(_STATES.get(cid, {'constraints': {}, 'trace': None, 'phase': 'IDLE'}))
    if body.get('trace'):
        state['trace'] = api._trusted_trace(body, planner)
        state['constraints'] = _constraints(state['trace'])
    reference = _reference(body, state.get('trace'))
    text = message.lower().strip()
    def finish(result):
        if result.get('trace'):
            state['trace'] = result['trace']
            state['constraints'] = _constraints(result['trace'])
        state['updated'] = time.monotonic()
        with _LOCK:
            _STATES[cid] = copy.deepcopy(state)
        return {**result, 'conversation_id': cid, 'source': 'grok' if result.get('provider') == 'grok' else 'local', 'phase': state['phase']}
    if text in ['reset', 'start over', 'clear plan', 'clear route']:
        state.update(constraints={}, trace=None, phase='IDLE')
        return finish({'reply': 'Trip cleared. Where would you like to go?', 'provider': 'template', 'verified': True, 'action': 'clear_path'})
    if re.fullmatch(r'(?:stop|stop walking|end navigation|end trip|stop the simulation)[.!]?', text):
        state['phase'] = 'ENDED'
        return finish({'reply': 'Navigation stopped. Your route remains available.', 'provider': 'template', 'verified': True, 'action': 'stop_walk'})
    if re.fullmatch(r'(?:start|go|walk (?:it|that path|the route)|start (?:walking|navigation|the trip|the simulation)|navigate)[.!]?', text):
        if not state.get('trace'):
            return finish({'reply': 'Choose a destination before starting navigation.', 'provider': 'template', 'verified': True})
        state['phase'] = 'NAVIGATING'
        return finish({'reply': api._template(state['trace']), 'provider': 'template', 'verified': True, 'trace': state['trace'], 'action': 'walk'})
    weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    weekday = next((i for i, name in enumerate(weekdays) if name in text), None)
    day_request = any(phrase in text for phrase in ['plan my day', 'my schedule', 'my classes', 'daily schedule', 'plan my week', 'week schedule']) or (weekday is not None and any(x in text for x in ['route', 'plan', 'class', 'schedule']))
    if day_request:
        from server.calendar_service import week_bounds
        begin, end = week_bounds(body.get('week_of') or reference.date().isoformat())
        day = begin+dt.timedelta(days=weekday) if weekday is not None else reference.date()
        if 'tomorrow' in text:
            day += dt.timedelta(days=1)
        source = api._calendar_window(planner, begin, end, body)
        selected = [e for e in source['events'] if api._parse_iso(e['start']).astimezone(TZ).date() == day]
        planned = planner.day_schedule({'origin': body.get('origin') or state.get('constraints', {}).get('origin', 'student-center')}, selected)
        fragments = []
        for item in planned['items']:
            tr = item['trace']
            fragments.append(api._template(tr))
        reply = ' '.join(fragments) if fragments else 'There are no travel plans for this day. Check the event locations or choose another day.'
        return finish({'reply': reply, 'provider': 'template', 'verified': True, 'action': 'show_schedule',
                       'day_plan': {**planned, 'mode': source['mode']}, 'schedule_date': day.isoformat()})
    if any(x in text for x in ['next class', 'next event', 'calendar', 'leave now', 'will i make it', 'will i be fine', 'will i be on time', 'can i make it']):
        result = api.chat({**body, 'trace': state.get('trace')}, planner)
        if result.get('trace'):
            state['phase'] = 'PREVIEW'
            result['action'] = 'show_path'
        return finish(result)
    constraints = copy.deepcopy(state['constraints'])
    constraints.pop('evaluate_at', None)
    if body.get('origin') is not None and 'origin' not in constraints:
        constraints['origin'] = body['origin']
    constraints.setdefault('origin', 'student-center')
    patches = []
    queries = {}
    pair = re.search(r'\bfrom\s+(.+?)\s+to\s+(.+?)(?=\s+(?:by|before|at|avoid|in \d)\b|[,?!.]|$)', message, re.I)
    if pair:
        queries = {'origin': pair[1], 'destination': pair[2]}
    else:
        origin = re.search(r'\bfrom\s+(.+?)(?=\s+(?:by|before|at|avoid)\b|[,?!.]|$)', message, re.I)
        destination = re.search(r'\b(?:to|toward)\s+(.+?)(?=\s+(?:by|before|at|avoid|in \d)\b|[,?!.]|$)', message, re.I)
        if origin:
            queries['origin'] = origin[1]
        if destination:
            queries['destination'] = destination[1]
    if state.get('pending'):
        queries[state.pop('pending')] = message
    if not queries and not any(x in text for x in ['why', 'explain', 'stairs', 'by ', 'make it', ' at ', 'minutes', 'walk only', 'bus']):
        try:
            direct = planner.resolve_place(message)
            queries['destination'] = direct['id']
        except ValueError:
            pass
    for field, query in queries.items():
        place, clarification = _resolve(query, planner)
        if clarification:
            state['pending'] = field
            return finish({'reply': clarification['question'], 'clarification': clarification, 'provider': 'template', 'verified': True})
        constraints[field] = place
        patches.append(field)
    clock = _clock(message, reference)
    if clock:
        if re.search(r'\b(?:depart|leave) at\b', text):
            constraints.pop('arrive_by', None)
            constraints['depart_at'] = clock.isoformat()
        else:
            constraints.pop('depart_at', None)
            constraints['arrive_by'] = clock.isoformat()
        patches.append('time')
    if any(x in text for x in ['avoid stairs', 'no stairs', 'step-free', 'step free']):
        constraints['avoid_stairs'] = True
        patches.append('accessibility preference')
    elif any(x in text for x in ['stairs are fine', 'allow stairs']):
        constraints['avoid_stairs'] = False
        patches.append('accessibility preference')
    if 'walk only' in text or 'just walk' in text:
        constraints['preferred_mode'] = 'walk'
        patches.append('travel mode')
    elif 'prefer bus' in text or 'take the bus' in text:
        constraints['preferred_mode'] = 'bus'
        patches.append('travel mode')
    if not constraints.get('destination'):
        state['constraints'] = constraints
        return finish({'reply': 'Where would you like to go? Choose a building or stop, and optionally an arrival time.', 'provider': 'template', 'verified': True})
    if patches:
        if not constraints.get('arrive_by') and not constraints.get('depart_at'):
            constraints['depart_at'] = reference.isoformat()
        trace = planner.plan_trip(constraints)
        result = api.chat({'message': 'Explain the selected route.', 'trace': trace}, planner)
        result['changed'] = patches
        result['action'] = 'show_path'
        state['phase'] = 'PREVIEW'
    else:
        result = api.chat({**body, 'trace': state.get('trace')}, planner)
    return finish(result)
