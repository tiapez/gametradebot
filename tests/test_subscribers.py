import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet
from monitor import Subscribers, ProductMessage, TelegramRejected, process_commands


class SubscriberTests(unittest.TestCase):
    def test_encrypted_persistence_wrong_key_and_stop_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'subscribers.enc'
            key = Fernet.generate_key()
            store = Subscribers(path, '123456789', key)
            self.assertNotIn(b'123456789', path.read_bytes())
            self.assertIn('123456789', Subscribers(path, key=key).users)
            with self.assertRaises(ValueError):
                Subscribers(path, key=Fernet.generate_key())
            store.unsubscribe('123456789')
            self.assertEqual(Subscribers(path, '123456789', key).users, {})

    @patch('monitor.time.sleep')
    def test_partial_delivery_retry_and_blocked_user(self, _):
        with tempfile.TemporaryDirectory() as folder:
            store = Subscribers(Path(folder) / 's.enc', key=Fernet.generate_key())
            for chat in ('1', '2', '3'):
                store.subscribe(chat)
            message = ProductMessage('Novita')
            message.key = 'Naruto:1'
            store.enqueue(message)
            delivered = []
            def api(method, payload, token):
                chat = payload['chat_id']
                if chat == '1':
                    raise TelegramRejected(403)
                if chat == '2':
                    raise RuntimeError('timeout')
                delivered.append(chat)
            with self.assertRaises(RuntimeError):
                store.deliver('fake', api)
            self.assertEqual(delivered, ['3'])
            self.assertNotIn('1', store.users)
            self.assertTrue(store.users['2'])
            self.assertFalse(store.users['3'])
            store.deliver('fake', lambda m, p, t: delivered.append(p['chat_id']))
            self.assertEqual(delivered, ['3', '2'])

    @patch('monitor.time.sleep')
    def test_private_start_stop_and_independent_replies(self, _):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = Subscribers(root / 's.enc', key=Fernet.generate_key())
            state = root / 'state.json'
            state.write_text(json.dumps({'Naruto': {}, 'One Piece': {}}))
            sequence = [('1', '/start', 'private'), ('1', '/start', 'private'),
                        ('2', '/start', 'private'), ('1', '/prodotti', 'private'),
                        ('1', '/londra26-27', 'private'),
                        ('-3', '/start', 'group'), ('1', '/stop', 'private')]
            updates = [{'update_id': i, 'message': {'chat': {'id': chat, 'type': kind}, 'text': cmd}}
                       for i, (chat, cmd, kind) in enumerate(sequence)]
            replies = []
            def api(method, payload, token):
                if method == 'getUpdates':
                    return updates
                replies.append((payload['chat_id'], payload['text']))
            process_commands(state, root / 'offset.json', 'fake', '', api, subscribers=store)
            self.assertEqual(set(store.users), {'2'})
            self.assertFalse(any(chat == '-3' for chat, _ in replies))
            self.assertTrue(all(chat == '1' for chat, text in replies if text.startswith(('Naruto:', 'One Piece:'))))
            self.assertTrue(any(chat == '1' and 'Calendario Bandai' in text for chat, text in replies))
            self.assertEqual(json.loads((root / 'offset.json').read_text()), len(sequence))


if __name__ == '__main__':
    unittest.main()
