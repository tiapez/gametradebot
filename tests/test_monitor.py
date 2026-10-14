import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from monitor import parse_page, collect, update_category, product_messages, process_commands


def page(items="", total=0, links=""):
    return f'<div id="listaarticoli"><div>{items}</div></div><div class="pagination">{links}<span class="show-resuilt">Showing 0-0 of {total} result(s)</span></div>'


def product(pid, title="Test &amp; carte"):
    return f'<div class="product-title"><a href="/Product/{pid}/test">{title}</a></div>'


class MonitorTests(unittest.TestCase):
    def test_preorder_scoped_to_card(self):
        html = page('<div class="product-card PRE-ORDER">' + product(1) + '</div>'
                    + '<div class="product-card">' + product(2) + '</div>', 2)
        items, _, _ = parse_page(html)
        self.assertIs(items['1']['preorder'], True)
        self.assertIs(items['2']['preorder'], False)

    def test_report_old_state_and_preorder_filter(self):
        products = {'1': {'title': 'Old', 'url': 'url'},
                    '2': {'title': 'New', 'url': 'url', 'preorder': True}}
        messages = list(product_messages({'Naruto': products}, True, ['Naruto']))
        self.assertEqual(len(messages), 2)
        self.assertIn('New', messages[1])
        self.assertIn('non ancora rilevato', list(product_messages({'Naruto': {'1': products['1']}}, categories=['Naruto']))[1])

    @patch('monitor.time.sleep')
    def test_commands_authorization_offset_and_live_preorders(self, _):
        with tempfile.TemporaryDirectory() as folder:
            state, offset = Path(folder) / 'state.json', Path(folder) / 'offset.json'
            state.write_text('{"Naruto": {}}', encoding='utf-8')
            replies, fetched = [], []
            updates = [
                {'update_id': 1, 'message': {'chat': {'id': 999}, 'text': '/prenotazioni'}},
                {'update_id': 2, 'message': {'chat': {'id': 123}, 'text': '/prodotti'}},
                {'update_id': 3, 'message': {'chat': {'id': 123}, 'text': '/prenotazioni'}},
            ]
            def api(method, payload, token):
                if method == 'getUpdates':
                    return [u for u in updates if u['update_id'] >= payload['offset']]
                self.assertEqual(payload['chat_id'], '123')
                replies.append(payload['text'])
                return {}
            def fetch(url):
                fetched.append(url)
                return {'4': {'title': 'Preorder', 'url': 'url', 'preorder': True}}
            process_commands(state, offset, 'fake', '123', api, fetch)
            self.assertEqual(len(fetched), 2)
            self.assertEqual(json.loads(offset.read_text()), 4)
            self.assertEqual(state.read_text(), '{"Naruto": {}}')
            count = len(replies)
            process_commands(state, offset, 'fake', '123', api, fetch)
            self.assertEqual(len(replies), count)

    def test_excludes_recommendations_and_decodes_entities(self):
        items, _, total = parse_page(page(product(123), 1) + product(999))
        self.assertEqual(set(items), {"123"})
        self.assertEqual(items["123"]["title"], "Test & carte")
        self.assertEqual(total, 1)

    def test_empty_category(self):
        self.assertEqual(parse_page(page() + product(999))[0], {})

    def test_error_page_not_empty_catalog(self):
        with self.assertRaises(ValueError):
            parse_page('<html>Access denied</html>')
        with self.assertRaises(ValueError):
            parse_page(page(total=1))

    def test_pagination(self):
        url = "https://www.gametrade.it/Categoria/Naruto/"
        pages = {url: page(product(1), 2, '<a href="?page=2">2</a>'), url + '?page=2': page(product(2), 2)}
        self.assertEqual(set(collect(url, pages.__getitem__)), {"1", "2"})

    def test_incomplete_catalog_is_rejected(self):
        with self.assertRaises(ValueError):
            collect("https://www.gametrade.it/Categoria/Naruto/", lambda _: page(product(1), 2))

    @patch('monitor.time.sleep')
    def test_baseline_new_and_returning_products(self, _):
        state, messages = {}, []
        p = {"1": {"title": "Uno", "url": "https://example.com/1"}}
        update_category(state, "Naruto", {}, messages.append, lambda: None)
        update_category(state, "Naruto", p, messages.append, lambda: None)
        update_category(state, "Naruto", {}, messages.append, lambda: None)
        update_category(state, "Naruto", p, messages.append, lambda: None)
        self.assertEqual(len(messages), 1)
        update_category(state, "One Piece", p, messages.append, lambda: None)
        self.assertEqual(len(messages), 1)

    def test_failed_delivery_remains_unseen(self):
        state = {"Naruto": {}}
        def fail(_):
            raise RuntimeError('offline')
        with self.assertRaises(RuntimeError):
            update_category(state, "Naruto", {"1": {"title": "Uno", "url": "url"}}, fail, lambda: None)
        self.assertEqual(state, {"Naruto": {}})


if __name__ == '__main__':
    unittest.main()
