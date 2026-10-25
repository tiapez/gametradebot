import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from cryptography.fernet import Fernet
from monitor import ProductMessage, Subscribers, save
import op18


def article(date='November 6, 2026 onwards', overview='Original overview', apply='https://www.bandai-tcg-plus.com/event/'):
    return f'''<html><nav>outside</nav><article class="articleCol">
    <h2>4th Anniversary Event (OP-18 Release Event)</h2>
    <p>Celebrate the fourth anniversary.</p><h3>Details</h3><h4>Period</h4>
    <p>November 20 – December 17, 2026</p><h4>Overview</h4><p>{overview}</p>
    <h4>Format</h4><ul><li>Constructed</li><li>Sealed</li><li>Standard</li></ul>
    <h3>Prize List</h3><h4>Participation</h4><p>Tournament Pack</p>
    <img src="/images/prize.webp"><h3>Application Method</h3>
    <p>Players apply through TCG+.</p><h4>Player Application Period</h4><p>{date}</p>
    <a href="{apply}">Apply on TCG+!</a><h3>Tournament Rules</h3><p>Read the rules.</p>
    </article><footer>outside changed freely</footer></html>'''


class Op18Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'op18.json'
        self.store = Subscribers(self.root / 'users.enc', '123', Fernet.generate_key())

    def check(self, html=article(), now='2026-10-25T12:00:00+00:00'):
        return op18.run_check(self.path, lambda _: html, self.store, ProductMessage, save,
                              datetime.fromisoformat(now))

    def test_registration_date_and_status(self):
        state = self.check()
        self.assertEqual(state['registration']['at'], '2026-11-06T00:00:00+01:00')
        text = op18.status_text(self.path)
        self.assertIn('06/11/2026', text)
        self.assertIn('Orario: non indicato', text)
        self.assertIn('bandai-tcg-plus.com/event/', text)

    def test_first_baseline_and_repeat_are_silent(self):
        self.check()
        self.check()
        self.assertFalse(self.store.users['123'])

    def test_content_change_alerts_once(self):
        self.check()
        self.check(article(overview='Updated overview'))
        pending = self.store.users['123']
        self.assertEqual(len(pending), 1)
        text = next(iter(pending.values()))['text']
        self.assertIn('Original overview', text)
        self.assertIn('Updated overview', text)
        self.check(article(overview='Updated overview'))
        self.assertEqual(len(pending), 1)

    def test_reminder_starts_at_midnight_italy_and_not_after_opening(self):
        self.check(now='2026-11-04T22:59:00+00:00')
        self.assertFalse(self.store.users['123'])
        self.check(now='2026-11-04T23:17:00+00:00')
        self.assertEqual(len(self.store.users['123']), 1)
        self.assertIn('aprono domani', next(iter(self.store.users['123'].values()))['text'])
        self.store.users['123'].clear()
        self.check(now='2026-11-05T23:01:00+00:00')
        self.assertFalse(self.store.users['123'])

    def test_changed_date_replaces_pending_reminder(self):
        self.check(now='2026-11-04T23:17:00+00:00')
        old_key = next(iter(self.store.users['123']))
        self.check(article(date='November 8, 2026 onwards'), now='2026-11-05T10:00:00+00:00')
        self.assertNotIn(old_key, self.store.users['123'])
        self.assertTrue(any(key.startswith('op18:change:') for key in self.store.users['123']))
        self.assertFalse(any(key.startswith('op18:reminder:') for key in self.store.users['123']))

    def test_unknown_date_suspends_reminder_and_preserves_snapshot(self):
        self.check()
        with self.assertRaises(ValueError):
            self.check(article(date='Coming soon'))
        state = json.loads(self.path.read_text())
        self.assertTrue(state['schedule_error'])
        self.assertIsNone(state['registration'])
        self.assertTrue(any(key.startswith('op18:schedule-error:') for key in self.store.users['123']))

    def test_invalid_page_does_not_replace_state(self):
        self.check()
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.check('<html>Service unavailable</html>')
        self.assertEqual(before, self.path.read_bytes())


if __name__ == '__main__':
    unittest.main()
