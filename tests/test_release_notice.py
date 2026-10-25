import tempfile
import unittest
from pathlib import Path
from cryptography.fernet import Fernet
from monitor import ProductMessage, Subscribers, save
import release_notice


class ReleaseNoticeTests(unittest.TestCase):
    def test_enqueues_once_for_existing_subscribers(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = Subscribers(root / 'users.enc', key=Fernet.generate_key())
            store.subscribe('1')
            store.subscribe('2')
            state = root / 'releases.json'
            self.assertTrue(release_notice.enqueue_once(state, store, ProductMessage, save))
            self.assertEqual(len(store.users['1']), 1)
            self.assertEqual(len(store.users['2']), 1)
            self.assertIn('Bot aggiornato e riavviato', next(iter(store.users['1'].values()))['text'])
            self.assertFalse(release_notice.enqueue_once(state, store, ProductMessage, save))
            self.assertEqual(len(store.users['1']), 1)

    def test_no_subscribers_still_marks_release_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = Subscribers(root / 'users.enc', key=Fernet.generate_key())
            state = root / 'releases.json'
            self.assertTrue(release_notice.enqueue_once(state, store, ProductMessage, save))
            store.subscribe('later')
            self.assertFalse(release_notice.enqueue_once(state, store, ProductMessage, save))
            self.assertFalse(store.users['later'])


if __name__ == '__main__':
    unittest.main()
