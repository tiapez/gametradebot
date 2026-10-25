"""Monitor dell'articolo e aperture registrazioni London 2026-2027."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from zoneinfo import ZoneInfo
from urllib.parse import urljoin

URL = 'https://www.bandaicardgames-fest.com/26-27/en/london/news/london-pre-registrationd.html'
MONTHS = 'January February March April May June July August September October November December'.split()
DATE = re.compile(r'(\d{1,2})(?:st|nd|rd|th)?\s+(' + '|'.join(MONTHS) +
                  r')(?:,?\s+(20\d{2}))?,?\s+(\d{1,2}):(\d{2})\s*(am|pm)\s+(GMT|BST|UTC)', re.I)


class Article(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.closed = False
        self.skip = 0
        self.parts = []
        self.lines = []
        self.assets = []

    def flush(self):
        line = ' '.join(''.join(self.parts).split())
        if line:
            self.lines.append(line)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'article':
            self.active = True
        if not self.active:
            return
        if tag in ('script', 'style'):
            self.skip += 1
        if self.skip:
            return
        if tag in ('div', 'p', 'li', 'br', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.flush()
        attrs = dict(attrs)
        value = attrs.get('href') if tag == 'a' else attrs.get('src') if tag == 'img' else None
        if value:
            self.assets.append(urljoin(URL, value))

    def handle_endtag(self, tag):
        if not self.active:
            return
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
        if self.skip:
            return
        if tag in ('div', 'p', 'li', 'h2', 'h3', 'h4', 'h5', 'h6', 'article'):
            self.flush()
        if tag == 'article':
            self.active = False
            self.closed = True

    def handle_data(self, data):
        if self.active and not self.skip:
            self.parts.append(data)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def parse_article(html):
    parser = Article()
    parser.feed(html)
    if not parser.closed or not any('Pre-Registration' in line for line in parser.lines) or len(parser.lines) < 10:
        raise ValueError('Articolo Bandai incompleto o non riconosciuto')
    return {'lines': parser.lines, 'assets': sorted(set(parser.assets))}


def extract_events(snapshot):
    lines = snapshot['lines']
    try:
        start = lines.index('Registration Dates, Links')
    except ValueError:
        raise ValueError('Sezione orari Bandai non riconosciuta: promemoria sospesi') from None
    events = []
    for i, line in enumerate(lines[start + 1:], start + 1):
        # Only parse the registration section, not incidental dates in the legal notes.
        if line in ('On Site', 'On-demand side events'):
            break
        matches = list(DATE.finditer(line))
        if (re.search(r'\d+:\d+|Sold on|\d+(?:st|nd|rd|th)\s+(?:' + '|'.join(MONTHS) + ')', line, re.I)
                and not matches):
            raise ValueError('Formato data Bandai cambiato: promemoria sospesi')
        for match in matches:
            day, month, year, hour, minute, ampm, zone = match.groups()
            month_number = [m.lower() for m in MONTHS].index(month.lower()) + 1
            # This specific edition runs across 2026/2027, not the current system year.
            year = int(year) if year else (2026 if month_number >= 7 else 2027)
            hour = int(hour)
            if not 1 <= hour <= 12:
                raise ValueError('Ora Bandai non valida')
            hour = hour % 12 + (12 if ampm.lower() == 'pm' else 0)
            tz = timezone(timedelta(hours=1 if zone.upper() == 'BST' else 0))
            when = datetime(year, month_number, int(day), hour, int(minute), tzinfo=tz).astimezone(timezone.utc)
            suffix = line[match.end():].strip(' =')
            label = suffix or (lines[i + 1] if i + 1 < len(lines) else 'Apertura registrazioni')
            if 'Europe Finals' in label:
                label = 'Finals, Last Chance Qualifier e ingresso generale'
            elif 'On Site Retail' in label:
                label = 'Biglietti On Site Retail'
            event = {'label': label, 'at': when.isoformat()}
            event['id'] = digest(event)[:24]
            events.append(event)
    if not events:
        raise ValueError('Nessun orario Bandai leggibile: promemoria sospesi')
    return sorted({e['id']: e for e in events}.values(), key=lambda e: e['at'])


def event_line(event):
    when = datetime.fromisoformat(event['at'])
    italy = when.astimezone(ZoneInfo('Europe/Rome'))
    london = when.astimezone(ZoneInfo('Europe/London'))
    return (f"{event['label']}\n{italy:%d/%m/%Y ore %H:%M} (Italia)"
            f" — {london:%H:%M} {london.tzname()} (Londra)")


def run_check(path, fetch, subscribers, message_type, save, now=None):
    now = now or datetime.now(timezone.utc)
    snapshot = parse_article(fetch(URL))
    state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    old = state.get('snapshot')
    revision = state.get('revision', 0)
    if old is not None and old != snapshot:
        revision += 1
        removed = [line for line in old['lines'] if line not in snapshot['lines']]
        added = [line for line in snapshot['lines'] if line not in old['lines']]
        # Bounded excerpts with an explicit indication that this is a summary.
        text = 'Pagina Bandai London modificata. Riepilogo delle differenze:\n'
        if removed:
            text += '\nPrima: ' + ' | '.join(removed)[:1100]
        if added:
            text += '\nOra: ' + ' | '.join(added)[:1100]
        if old['assets'] != snapshot['assets']:
            text += '\nSono cambiati anche link o riferimenti alle immagini.'
        text += '\nControlla la pagina ufficiale per tutti i dettagli:\n' + URL
        message = message_type(text)
        message.key = f'bandai:change:{revision}:{digest(snapshot)[:16]}'
        subscribers.enqueue(message)
    state.update(snapshot=snapshot, revision=revision, checked_at=now.isoformat())
    try:
        events = extract_events(snapshot)
    except ValueError:
        # Do not keep sending an obsolete schedule after an unrecognized page change.
        subscribers.prune_bandai_reminders(set())
        if not state.get('schedule_error'):
            message = message_type('Bandai London: il formato delle date è cambiato. Promemoria sospesi; verifica la pagina ufficiale.\n' + URL)
            message.key = 'bandai:schedule-error:' + digest(snapshot)[:16]
            subscribers.enqueue(message)
        state['schedule_error'] = True
        state['events'] = []
        save(path, state)
        raise
    state.update(events=events, schedule_error=False)
    sent = state.setdefault('reminders', [])
    valid = {f"bandai:reminder:{e['id']}" for e in events if datetime.fromisoformat(e['at']) > now}
    subscribers.prune_bandai_reminders(valid)
    for event in events:
        when = datetime.fromisoformat(event['at'])
        if when - timedelta(days=1) <= now < when and event['id'] not in sent:
            message = message_type('Promemoria Bandai London — apertura registrazioni:\n\n' + event_line(event))
            message.key = f"bandai:reminder:{event['id']}"
            message.expires_at = when.isoformat()
            subscribers.enqueue(message)
            sent.append(event['id'])
    save(path, state)
    return state


def calendar_text(path):
    if not path.exists():
        return 'Calendario Bandai non ancora inizializzato: attendi il prossimo controllo.'
    state = json.loads(path.read_text(encoding='utf-8'))
    if state.get('schedule_error'):
        return 'Calendario Bandai da verificare: promemoria sospesi.\n' + URL
    future = [e for e in state.get('events', []) if datetime.fromisoformat(e['at']) > datetime.now(timezone.utc)]
    return ('Aperture registrazioni Bandai London (ultimo controllo: ' + state['checked_at'] + '):\n\n'
            + ('\n\n'.join(event_line(e) for e in future) or 'Nessuna apertura futura rilevata.'))
