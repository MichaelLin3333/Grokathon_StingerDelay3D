"""Bounded calendar normalization and weekly/daily recurrence, without network I/O."""
import datetime as dt
import hashlib
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TZ = ZoneInfo('America/New_York')
DAYS = {'MO': 0, 'TU': 1, 'WE': 2, 'TH': 3, 'FR': 4, 'SA': 5, 'SU': 6}


def _timestamp(value, params):
    if re.fullmatch(r'\d{8}', value):
        return None
    zone = params.get('TZID', 'America/New_York').strip('"')
    try:
        tz = dt.timezone.utc if value.endswith('Z') else ZoneInfo(zone)
        result = dt.datetime.strptime(value.rstrip('Z'), '%Y%m%dT%H%M%S').replace(tzinfo=tz)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError('Calendar has an invalid timestamp or unsupported timezone.') from exc
    return result


def _unescape(value):
    return re.sub(r'\\([,;\\])', r'\1', value.replace('\\n', ' ').replace('\\N', ' '))


def parse_ics(text):
    if not isinstance(text, str) or len(text.encode()) > 500000:
        raise ValueError('Choose a calendar smaller than 500 KB.')
    text = re.sub(r'\r?\n[ \t]', '', text)
    events, warnings = [], []
    for block in re.findall(r'BEGIN:VEVENT\s*(.*?)END:VEVENT', text, re.S):
        fields, excluded = {}, []
        for line in block.splitlines():
            key, sep, value = line.partition(':')
            if not sep:
                continue
            pieces = key.split(';')
            params = dict(p.split('=', 1) for p in pieces[1:] if '=' in p)
            name = pieces[0].upper()
            if name == 'EXDATE':
                excluded.extend(_timestamp(v, params).isoformat() for v in value.strip().split(',') if v)
            else:
                fields[name] = (value.strip(), params)
        if fields.get('STATUS', ('', {}))[0] == 'CANCELLED':
            continue
        if 'DTSTART' not in fields:
            continue
        start = _timestamp(*fields['DTSTART'])
        if start is None:
            warnings.append('All-day events are excluded from travel planning.')
            continue
        if 'RECURRENCE-ID' in fields:
            raise ValueError('This calendar has edited recurring instances. Use Google Calendar or an export with expanded occurrences.')
        if 'DTEND' in fields:
            end = _timestamp(*fields['DTEND'])
        elif 'DURATION' in fields:
            match = re.fullmatch(r'P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?', fields['DURATION'][0])
            if not match:
                raise ValueError('Unsupported calendar event duration.')
            days, hours, minutes, seconds = [int(x or 0) for x in match.groups()]
            end = start + dt.timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
        else:
            raise ValueError('Timed events need DTEND or DURATION.')
        if end is None or end <= start:
            raise ValueError('Each event must end after its start.')
        rule = fields.get('RRULE', ('', {}))[0]
        if rule:
            validate_rule(rule)
        uid = fields.get('UID', (hashlib.sha256(block.encode()).hexdigest()[:20], {}))[0]
        events.append({'id': uid[:120], 'title': _unescape(fields.get('SUMMARY', ('Calendar event', {}))[0])[:200],
            'location': _unescape(fields.get('LOCATION', ('', {}))[0])[:300],
            'start': start.isoformat(), 'end': end.isoformat(), 'timezone': str(start.tzinfo),
            'recurrence': rule, 'exdates': excluded, 'source': 'ics'})
        if len(events) > 200:
            raise ValueError('Import at most 200 recurring event definitions.')
    if not events:
        raise ValueError('No timed events were found in this calendar.')
    return events, sorted(set(warnings))


def validate_rule(text):
    try:
        rule = dict(piece.split('=', 1) for piece in text.split(';') if piece)
    except ValueError as exc:
        raise ValueError('Invalid recurrence rule.') from exc
    if set(rule) - {'FREQ', 'BYDAY', 'INTERVAL', 'UNTIL', 'COUNT', 'WKST'}:
        raise ValueError('Import supports daily/weekly recurrence. Use Google Calendar for more complex rules.')
    if rule.get('FREQ') not in ['WEEKLY', 'DAILY']:
        raise ValueError('Only daily and weekly calendar recurrence is supported.')
    if 'BYDAY' in rule and any(d not in DAYS for d in rule['BYDAY'].split(',')):
        raise ValueError('Unsupported BYDAY recurrence value.')
    for key in ['INTERVAL', 'COUNT']:
        try:
            if key in rule and not 1 <= int(rule[key]) <= 10000:
                raise ValueError()
        except ValueError as exc:
            raise ValueError('Recurrence interval/count must be a positive bounded integer.') from exc
    if rule.get('WKST', 'MO') not in DAYS:
        raise ValueError('Invalid recurrence week start.')
    return rule


def expand(events, start_date, end_date):
    if isinstance(start_date, str):
        start_date = dt.date.fromisoformat(start_date)
    if isinstance(end_date, str):
        end_date = dt.date.fromisoformat(end_date)
    if not 0 < (end_date-start_date).days <= 42:
        raise ValueError('Calendar expansion needs a range of at most six weeks.')
    result = []
    for event in events:
        original = dt.datetime.fromisoformat(event['start'])
        end = dt.datetime.fromisoformat(event['end'])
        zone = ZoneInfo(event.get('timezone') or 'America/New_York')
        original = original.astimezone(zone)
        duration = end - original
        text = event.get('recurrence')
        if not text:
            if start_date <= original.astimezone(TZ).date() < end_date:
                result.append(dict(event))
            continue
        rule = validate_rule(text)
        interval, maximum = int(rule.get('INTERVAL', 1)), int(rule.get('COUNT', 10000))
        weekdays = {DAYS[x] for x in rule.get('BYDAY', list(DAYS)[original.weekday()]).split(',')}
        excluded = {dt.datetime.fromisoformat(x).astimezone(dt.timezone.utc) for x in event.get('exdates', [])}
        until = None
        if rule.get('UNTIL'):
            value = rule['UNTIL']
            until = (_timestamp(value, {'TZID': str(zone)}) if 'T' in value else
                     dt.datetime.combine(dt.datetime.strptime(value, '%Y%m%d').date(), dt.time.max, zone))
        day, count = original.date(), 0
        week_start = DAYS[rule.get('WKST', 'MO')]
        anchor = day - dt.timedelta(days=(day.weekday()-week_start) % 7)
        final = end_date + dt.timedelta(days=1)  # handle a different event timezone
        if (final-day).days > 36600:
            raise ValueError('Calendar recurrence begins too far in the past to expand safely.')
        while day <= final and count < maximum:
            delta = (day-original.date()).days
            week = ((day-dt.timedelta(days=(day.weekday()-week_start) % 7))-anchor).days // 7
            matches = (delta % interval == 0 and ('BYDAY' not in rule or day.weekday() in weekdays)) if rule['FREQ'] == 'DAILY' else week % interval == 0 and day.weekday() in weekdays
            if matches:
                occurrence = dt.datetime.combine(day, original.timetz()).replace(tzinfo=zone)
                if occurrence >= original:
                    if until and occurrence > until:
                        break
                    count += 1
                    if occurrence.astimezone(dt.timezone.utc) not in excluded and start_date <= occurrence.astimezone(TZ).date() < end_date:
                        result.append({**event, 'id': event['id']+'@'+day.isoformat(),
                            'start': occurrence.isoformat(), 'end': (occurrence+duration).isoformat()})
            day += dt.timedelta(days=1)
        if len(result) > 1000:
            raise ValueError('Too many calendar occurrences in this range.')
    return sorted(result, key=lambda e: dt.datetime.fromisoformat(e['start']))


def week_bounds(value=None):
    date = dt.date.fromisoformat(value) if value else dt.datetime.now(TZ).date()
    monday = date-dt.timedelta(days=date.weekday())
    return monday, monday+dt.timedelta(days=7)
