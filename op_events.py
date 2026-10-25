"""Monitor della pagina eventi ufficiale ONE PIECE CARD GAME."""
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

URL = 'https://en.onepiece-cardgame.com/events/'


def clean(text):
    return ' '.join(text.replace('\xa0', ' ').replace('\u200b', '').split())


def canonical(url):
    parts = urlsplit(urljoin(URL, url))
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, '', ''))


class EventsParser(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
            'meta', 'param', 'source', 'track', 'wbr'}
    def __init__(self):
        super().__init__()
        self.stack = []
        self.card = None
        self.card_depth = None
        self.capture = None
        self.parts = []
        self.events = []
        self.found_past_events = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get('class', '').split()
        if tag == 'a' and urlsplit(urljoin(URL, attrs.get('href', ''))).path.endswith('/events/list_end.php'):
            self.found_past_events = True
        if tag not in self.VOID:
            self.stack.append(tag)
        if self.card is None and 'linkCard' in classes and tag in ('a', 'div'):
            self.card = {'title': '', 'period': '', 'category': [], 'regulation': '',
                         'description': '', 'url': '', 'image_url': ''}
            self.card_depth = len(self.stack)
            if tag == 'a':
                self.card['url'] = canonical(attrs.get('href', ''))
        if self.card is None:
            return
        if tag == 'a' and attrs.get('href') and not self.card['url']:
            link = canonical(attrs['href'])
            if urlsplit(link).hostname == 'en.onepiece-cardgame.com':
                self.card['url'] = link
        if tag == 'img' and not self.card['image_url']:
            image = attrs.get('data-src') or attrs.get('src') or ''
            if image:
                self.card['image_url'] = canonical(image)
        field = None
        if tag == 'h4':
            field = 'title'
        elif tag == 'p' and 'linkCardDate' in classes:
            field = 'period'
        elif tag == 'p' and 'linkCardRegulation' in classes:
            field = 'regulation'
        elif tag == 'p' and 'linkCardTxt' in classes:
            field = 'description'
        elif tag == 'span' and 'type' in classes:
            field = 'category'
        if field:
            self.capture, self.parts = field, []

    def handle_data(self, data):
        if self.card is not None and self.capture:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if self.card is not None and self.capture:
            expected = {'title': 'h4', 'period': 'p', 'regulation': 'p',
                        'description': 'p', 'category': 'span'}[self.capture]
            if tag == expected:
                value = clean(''.join(self.parts))
                if self.capture == 'category':
                    if value and value not in self.card['category']:
                        self.card['category'].append(value)
                else:
                    prefix = {'period': 'Event Period:', 'regulation': 'Regulation:'}.get(self.capture)
                    if prefix and value.lower().startswith(prefix.lower()):
                        value = clean(value[len(prefix):])
                    self.card[self.capture] = value
                self.capture, self.parts = None, []
        if self.card is not None and self.stack and len(self.stack) == self.card_depth and tag == self.stack[-1]:
            if self.card['title'] and self.card['period'] and self.card['url']:
                self.card['category'] = ' · '.join(self.card['category']) or 'CHAMPIONSHIP'
                self.events.append(self.card)
            self.card, self.card_depth = None, None
            self.capture, self.parts = None, []
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()


def parse_page(html):
    parser = EventsParser()
    parser.feed(html)
    # Discovery cards duplicate some entries; URL is the stable event identity.
    events = {}
    for event in parser.events:
        old = events.get(event['url'])
        if old is None or sum(bool(v) for v in event.values()) > sum(bool(v) for v in old.values()):
            events[event['url']] = event
    if not parser.found_past_events or not events:
        raise ValueError('Pagina eventi One Piece incompleta o non riconosciuta')
    return dict(sorted(events.items()))


def fingerprint(event):
    return hashlib.sha256(json.dumps(event, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def event_message(event, status=None, include_url=True):
    parts = []
    if status:
        parts.append(status)
    parts.extend([event['title'], 'Periodo: ' + event['period'], 'Categoria: ' + event['category']])
    if event.get('regulation'):
        parts.append('Regolamento: ' + event['regulation'])
    if event.get('description'):
        parts.append(event['description'])
    if include_url:
        parts.append(event['url'])
    return '\n'.join(parts)


def diff_summary(old, new):
    labels = {'title': 'Nome', 'period': 'Periodo', 'category': 'Categoria',
              'regulation': 'Regolamento', 'description': 'Descrizione',
              'url': 'Link', 'image_url': 'Immagine'}
    changes = []
    for field, label in labels.items():
        if old.get(field) != new.get(field):
            before = old.get(field) or '—'
            after = new.get(field) or '—'
            changes.append(f'{label}: {before[:450]} → {after[:450]}')
    return '\n'.join(changes)


def run_check(path, fetch, subscribers, message_type, save, now=None):
    current = parse_page(fetch(URL))
    state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    previous = state.get('events')
    revision = state.get('revision', 0)
    if previous is not None:
        for url, event in current.items():
            if url not in previous:
                revision += 1
                message = message_type(event_message(event, 'Nuovo evento ONE PIECE CARD GAME'), event.get('image_url'))
                message.key = f'op-event:new:{revision}:{fingerprint(event)}'
                subscribers.enqueue(message)
            elif previous[url] != event:
                revision += 1
                text = ('Evento ONE PIECE CARD GAME aggiornato\n\n' + event['title'] + '\n'
                        + diff_summary(previous[url], event) + '\n' + event['url'])
                message = message_type(text[:3900], event.get('image_url'))
                message.key = f'op-event:update:{revision}:{fingerprint(event)}'
                subscribers.enqueue(message)
    state = {'events': current, 'revision': revision,
             'checked_at': (now.isoformat() if now else __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat())}
    save(path, state)
    return state


def active_messages(path, max_chars=3500):
    if not Path(path).exists():
        return ['Eventi One Piece non ancora inizializzati: attendi il prossimo controllo.']
    state = json.loads(Path(path).read_text(encoding='utf-8'))
    events = list(state.get('events', {}).values())
    if not events:
        return ['Nessun evento attivo rilevato.']
    messages = [f'Eventi ONE PIECE CARD GAME attivi: {len(events)}\nUltimo controllo: {state.get("checked_at", "—")}']
    chunk = ''
    for event in events:
        item = '\n\n' + event_message(event, include_url=True)
        if chunk and len(chunk) + len(item) > max_chars:
            messages.append(chunk.strip())
            chunk = ''
        chunk += item
    if chunk:
        messages.append(chunk.strip())
    return messages
