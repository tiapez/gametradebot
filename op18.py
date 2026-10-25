"""Monitor pagina OP-18 e promemoria apertura iscrizioni giocatori."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

URL = 'https://en.onepiece-cardgame.com/events/store-tournament-op18.html'
ITALY = ZoneInfo('Europe/Rome')
APPLICATION_DATE = re.compile(
    r'Player Application Period\s+(' +
    '|'.join('January February March April May June July August September October November December'.split()) +
    r')\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})(?:\s+onwards)?', re.I)


def clean(text):
    return ' '.join(text.replace('\xa0', ' ').replace('\u200b', '').split())


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.closed = False
        self.skip = 0
        self.parts = []
        self.lines = []
        self.assets = []

    def flush(self):
        value = clean(''.join(self.parts))
        if value:
            self.lines.append(value)
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
    parser = ArticleParser()
    parser.feed(html)
    joined = ' '.join(parser.lines)
    if (not parser.closed or '4th Anniversary Event' not in joined
            or 'Player Application Period' not in joined or len(parser.lines) < 15):
        raise ValueError('Pagina OP-18 incompleta o non riconosciuta')
    return {'lines': parser.lines, 'assets': sorted(set(parser.assets))}


def registration(snapshot):
    joined = ' '.join(snapshot['lines'])
    match = APPLICATION_DATE.search(joined)
    if not match:
        raise ValueError('Data iscrizione OP-18 non riconosciuta: promemoria sospeso')
    month, day, year = match.groups()
    month_number = [m.lower() for m in
                    'January February March April May June July August September October November December'.split()].index(month.lower()) + 1
    when = datetime(int(year), month_number, int(day), tzinfo=ITALY)
    apply_links = [url for url in snapshot['assets'] if 'bandai-tcg-plus.com/event' in url]
    return {'at': when.isoformat(), 'label': 'Apertura iscrizioni giocatori OP-18',
            'apply_url': apply_links[0] if apply_links else ''}


def diff_text(old, new):
    removed = [line for line in old['lines'] if line not in new['lines']]
    added = [line for line in new['lines'] if line not in old['lines']]
    parts = ['Pagina OP-18 modificata. Riepilogo delle differenze:']
    if removed:
        parts.append('Prima: ' + ' | '.join(removed)[:1100])
    if added:
        parts.append('Ora: ' + ' | '.join(added)[:1100])
    if old['assets'] != new['assets']:
        parts.append('Sono cambiati anche collegamenti o riferimenti alle immagini.')
    parts.append('Controlla la pagina ufficiale per tutti i dettagli:\n' + URL)
    return '\n\n'.join(parts)


def registration_text(item, checked_at=None):
    when = datetime.fromisoformat(item['at']).astimezone(ITALY)
    text = (f"OP-18 — iscrizioni giocatori\nApertura indicata: {when:%d/%m/%Y}"
            "\nOrario: non indicato sulla pagina ufficiale")
    if item.get('apply_url'):
        text += '\nIscrizione: ' + item['apply_url']
    text += '\nPagina ufficiale: ' + URL
    if checked_at:
        text += '\nUltimo controllo: ' + checked_at
    return text


def run_check(path, fetch, subscribers, message_type, save, now=None):
    now = now or datetime.now(timezone.utc)
    snapshot = parse_article(fetch(URL))
    state = json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else {}
    old = state.get('snapshot')
    revision = state.get('revision', 0)
    if old is not None and old != snapshot:
        revision += 1
        message = message_type(diff_text(old, snapshot))
        message.key = f'op18:change:{revision}:{digest(snapshot)[:16]}'
        subscribers.enqueue(message)
    state.update(snapshot=snapshot, revision=revision, checked_at=now.isoformat())
    try:
        item = registration(snapshot)
    except ValueError:
        subscribers.prune_pending('op18:reminder:', set())
        if not state.get('schedule_error'):
            message = message_type('OP-18: il formato della data di iscrizione è cambiato. Promemoria sospeso; verifica la pagina ufficiale.\n' + URL)
            message.key = 'op18:schedule-error:' + digest(snapshot)[:16]
            subscribers.enqueue(message)
        state.update(registration=None, schedule_error=True)
        save(path, state)
        raise
    state.update(registration=item, schedule_error=False)
    reminder_id = digest(item['at'])[:24]
    reminder_key = f'op18:reminder:{reminder_id}'
    opening = datetime.fromisoformat(item['at'])
    valid = {reminder_key} if opening.astimezone(timezone.utc) > now else set()
    subscribers.prune_pending('op18:reminder:', valid)
    sent = state.setdefault('reminders', [])
    reminder_start = (opening - timedelta(days=1)).astimezone(timezone.utc)
    if reminder_start <= now < opening.astimezone(timezone.utc) and reminder_id not in sent:
        message = message_type('Promemoria — iscrizioni OP-18 aprono domani\n\n' + registration_text(item))
        message.key = reminder_key
        message.expires_at = opening.astimezone(timezone.utc).isoformat()
        subscribers.enqueue(message)
        sent.append(reminder_id)
    save(path, state)
    return state


def status_text(path):
    path = Path(path)
    if not path.exists():
        return 'Monitor OP-18 non ancora inizializzato: attendi il prossimo controllo.'
    state = json.loads(path.read_text(encoding='utf-8'))
    if state.get('schedule_error') or not state.get('registration'):
        return 'Data di iscrizione OP-18 da verificare: promemoria sospeso.\n' + URL
    return registration_text(state['registration'], state.get('checked_at'))
