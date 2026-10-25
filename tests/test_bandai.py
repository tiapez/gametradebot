import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet
import bandai
from monitor import Subscribers, ProductMessage, save


def article(hour='9:00am', link='https://example.com/tickets'):
    return f'''<nav>ignored</nav><article><h2>Pre-Registration</h2>
    <h3>Tournament Schedule</h3><p>15th January (Friday)</p><p>One Piece</p>
    <h3>Registration Dates, Links</h3><h6>25th October, 9:00am GMT</h6>
    <p>Europe Finals</p><h6>10th January, {hour} GMT</h6><p>On Site Retail Tickets</p>
    <h6>Day prior the tournament</h6><p>Demo Tickets</p>
    <ul><li>Sold on 14th January 7:00pm GMT =15th (Friday) Demos</li>
    <li>Sold on 15th January 7:00pm GMT =16th (Saturday) Side Events/Demos</li>
    <li>Sold on 16th January 7:00pm GMT =17th (Sunday) Side Event/Demos</li></ul>
    <h6>On Site</h6><p>On-demand side events</p><a href="{link}">Tickets</a>
    <script>random()</script></article><footer>ignored</footer>'''


class BandaiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'bandai.json'
        self.store = Subscribers(Path(self.temp.name) / 'users.enc', '123', Fernet.generate_key())

    def check(self, html=article(), now='2026-10-25T12:00:00+00:00'):
        return bandai.run_check(self.path, lambda _: html, self.store, ProductMessage, save, datetime.fromisoformat(now))

    def test_dates_and_timezone(self):
        events = bandai.extract_events(bandai.parse_article(article()))
        self.assertEqual(len(events), 5)
        self.assertEqual(events[0]['at'], '2026-10-25T09:00:00+00:00')
        self.assertEqual(events[1]['at'], '2027-01-10T09:00:00+00:00')
        self.assertIn('10:00 (Italia)', bandai.event_line(events[1]))
        self.assertIn('20:00 (Italia)', bandai.event_line(events[2]))

    def test_normalization_and_non_article_changes(self):
        one = bandai.parse_article(article())
        two = bandai.parse_article(article().replace('ignored', 'changed').replace('random()', 'new()').replace('On Site Retail', 'On  Site\n Retail'))
        self.assertEqual(one, two)

    def test_first_check_no_backdated_alerts_and_no_duplicates(self):
        self.check()
        self.assertFalse(self.store.users['123'])
        self.check()
        self.assertFalse(self.store.users['123'])
        self.check(now='2027-01-09T08:59:00+00:00')
        self.assertFalse(self.store.users['123'])
        self.check(now='2027-01-09T09:17:00+00:00')
        self.assertEqual(len(self.store.users['123']), 1)
        self.store.users['123'].clear()  # Simulate successful delivery.
        self.check(now='2027-01-09T09:47:00+00:00')
        self.assertFalse(self.store.users['123'])

    def test_changed_date_replaces_pending_reminder(self):
        self.check(now='2027-01-09T09:17:00+00:00')
        old_key = next(iter(self.store.users['123']))
        self.check(article('11:00am'), now='2027-01-09T09:47:00+00:00')
        self.assertNotIn(old_key, self.store.users['123'])
        self.assertTrue(any(k.startswith('bandai:change:') for k in self.store.users['123']))
        self.check(article('11:00am'), now='2027-01-09T11:17:00+00:00')
        self.assertTrue(any(k.startswith('bandai:reminder:') for k in self.store.users['123']))

    def test_link_only_change_and_repeat(self):
        self.check()
        self.check(article(link='https://example.com/new'))
        self.assertEqual(len(self.store.users['123']), 1)
        self.check(article(link='https://example.com/new'))
        self.assertEqual(len(self.store.users['123']), 1)

    def test_invalid_page_preserves_state(self):
        self.check()
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.check('<html>Service unavailable</html>')
        self.assertEqual(before, self.path.read_bytes())

    def test_unknown_date_pauses_schedule_but_reports_change(self):
        self.check()
        with self.assertRaises(ValueError):
            self.check(article('09:00'))
        state = json.loads(self.path.read_text())
        self.assertTrue(state['schedule_error'])
        self.assertEqual(state['events'], [])
        self.assertEqual(len(self.store.users['123']), 2)

    @patch('monitor.time.sleep')
    def test_expired_delivery_is_dropped(self, _):
        msg = ProductMessage('Reminder')
        msg.key = 'bandai:reminder:old'
        msg.expires_at = '2000-01-01T09:00:00+00:00'
        self.store.enqueue(msg)
        calls = []
        self.store.deliver('fake', lambda *args: calls.append(args))
        self.assertEqual(calls, [])
        self.assertFalse(self.store.users['123'])


if __name__ == '__main__':
    unittest.main()
