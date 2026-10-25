import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from cryptography.fernet import Fernet
from monitor import ProductMessage, Subscribers, save
import op_events


def page(changed_period=None, extra=False, omit=None):
    cards = []
    for number in range(1, 10):
        if number == omit:
            continue
        period = changed_period if number == 2 and changed_period else f'November {number}, 2026'
        cards.append(f'''<li class="eventsColBox"><a class="linkCard"
          href="/events/event-{number}.html?tracking=ignored">
          <img src="placeholder.webp" data-src="/images/event-{number}.webp?cache=123">
          <span class="type">Tournament</span><h4>Event {number}</h4>
          <p class="linkCardDate"><span>Event Period:&nbsp;</span>{period}</p>
          <p class="linkCardRegulation"><span>Regulation:&nbsp;</span>Standard</p>
          <p class="linkCardTxt">Description {number}</p></a></li>''')
    if extra:
        cards.append('''<a class="linkCard" href="/events/new.html"><h4>New Event</h4>
          <p class="linkCardDate">Event Period: January 2027</p>
          <p class="linkCardTxt">New description</p></a>''')
    return ('<html><nav>ignored</nav><main>' + ''.join(cards)
            + '</main><a href="/events/list_end.php">PAST EVENTS</a><footer>ignored</footer></html>')


class OnePieceEventsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'events.json'
        self.store = Subscribers(self.root / 'users.enc', '123', Fernet.generate_key())

    def check(self, html):
        return op_events.run_check(self.path, lambda _: html, self.store, ProductMessage, save,
                                   datetime(2026, 10, 25, tzinfo=timezone.utc))

    def test_parser_normalizes_urls_and_fields(self):
        events = op_events.parse_page(page())
        event = events['https://en.onepiece-cardgame.com/events/event-1.html']
        self.assertEqual(len(events), 9)
        self.assertEqual(event['period'], 'November 1, 2026')
        self.assertEqual(event['category'], 'Tournament')
        self.assertEqual(event['regulation'], 'Standard')
        self.assertEqual(event['image_url'], 'https://en.onepiece-cardgame.com/images/event-1.webp')

    def test_first_baseline_is_silent_and_repeat_is_silent(self):
        self.check(page())
        self.assertFalse(self.store.users['123'])
        self.check(page())
        self.assertFalse(self.store.users['123'])

    def test_new_and_updated_events_alert_once(self):
        self.check(page())
        self.check(page(changed_period='December 2, 2026', extra=True))
        pending = self.store.users['123']
        self.assertEqual(len(pending), 2)
        self.assertTrue(any(key.startswith('op-event:new:') for key in pending))
        self.assertTrue(any(key.startswith('op-event:update:') for key in pending))
        texts = [item['text'] for item in pending.values()]
        self.assertTrue(any('November 2, 2026' in text and 'December 2, 2026' in text for text in texts))
        self.check(page(changed_period='December 2, 2026', extra=True))
        self.assertEqual(len(pending), 2)

    def test_removed_event_disappears_without_alert(self):
        self.check(page())
        state = self.check(page(omit=9))
        self.assertEqual(len(state['events']), 8)
        self.assertFalse(self.store.users['123'])

    def test_incomplete_page_preserves_previous_state(self):
        self.check(page())
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.check('<html>Service unavailable</html>')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.store.users['123'])

    def test_event_command_chunks_and_shows_all(self):
        self.check(page(extra=True))
        messages = op_events.active_messages(self.path, max_chars=400)
        self.assertGreater(len(messages), 2)
        output = '\n'.join(messages)
        self.assertIn('Eventi ONE PIECE CARD GAME attivi: 10', output)
        for number in range(1, 10):
            self.assertIn(f'Event {number}', output)
        self.assertIn('New Event', output)


if __name__ == '__main__':
    unittest.main()
