"""Gametrade -> Telegram. Python 3.11+, nessuna dipendenza esterna."""
import argparse
import json
import os
import re
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

BASE = "https://www.gametrade.it"
CATEGORIES = {"One Piece": BASE + "/Categoria/One_Piece/", "Naruto": BASE + "/Categoria/Naruto/"}


class CatalogParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.divs = []
        self.products = {}
        self.pages = set()
        self.current = None
        self.summary = []
        self.in_summary = False
        self.found_catalog = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if tag == "div":
            marker = attrs.get("id") == "listaarticoli"
            self.found_catalog |= marker
            self.divs.append("catalog" if marker else "title" if "product-title" in classes else "pages" if "pagination" in classes else "")
        if tag == "span" and "show-resuilt" in classes:
            self.in_summary = True
        if tag == "a":
            href = attrs.get("href", "")
            if "catalog" in self.divs and "title" in self.divs:
                match = re.fullmatch(r"/Product/(\d+)/[^?#]+", href)
                if match:
                    self.current = [match[1], urljoin(BASE, href), []]
            if "pages" in self.divs and href:
                self.pages.add(href)

    def handle_data(self, data):
        if self.current is not None:
            self.current[2].append(data)
        if self.in_summary:
            self.summary.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            pid, url, parts = self.current
            title = " ".join("".join(parts).split())
            if title:
                self.products[pid] = {"title": title, "url": url}
            self.current = None
        if tag == "span":
            self.in_summary = False
        if tag == "div" and self.divs:
            self.divs.pop()


def parse_page(html):
    parser = CatalogParser()
    parser.feed(html)
    summary = "".join(parser.summary)
    match = re.search(r"(?:of|di)\s+(\d+)\s+(?:result|risultat)", summary, re.I)
    if not parser.found_catalog or not match:
        raise ValueError("Pagina non riconosciuta: catalogo o conteggio assente")
    total = int(match[1])
    if total and not parser.products:
        raise ValueError("Il sito indica prodotti ma non sono leggibili")
    return parser.products, parser.pages, total


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": "GametradeProductMonitor/1.0", "Accept-Language": "en"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8")
        except OSError:
            if attempt == 2:
                raise RuntimeError("Impossibile leggere Gametrade") from None
            time.sleep(2 ** attempt)


def collect(url, fetch=download):
    pending, visited, products = [url], set(), {}
    expected = None
    while pending:
        page = pending.pop()
        if page in visited:
            continue
        if len(visited) >= 30:
            raise ValueError("Troppe pagine: controllo interrotto")
        visited.add(page)
        items, links, total = parse_page(fetch(page))
        if expected is not None and total != expected:
            raise ValueError("Catalogo cambiato durante la lettura: riprovare")
        expected = total
        products.update(items)
        for link in links:
            target = urljoin(page, link).split("#")[0]
            parsed = urlsplit(target)
            if parsed.scheme != "https" or parsed.netloc != "www.gametrade.it" or parsed.path.rstrip("/") != urlsplit(url).path.rstrip("/"):
                raise ValueError("Paginazione non riconosciuta")
            if target not in visited:
                pending.append(target)
    if len(products) != expected:
        raise ValueError("Catalogo incompleto: nessuno stato aggiornato")
    return products


def telegram(method, payload, token):
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except (OSError, ValueError):
        # Non stampare eccezioni urllib: l'URL contiene il token.
        raise RuntimeError("Telegram non raggiungibile o credenziali non valide") from None
    if not result.get("ok"):
        raise RuntimeError("Telegram ha rifiutato la richiesta")
    return result["result"]


def save(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def update_category(state, category, products, send, persist):
    if category not in state:
        state[category] = products.copy()
        persist()
        print(f"{category}: inizializzati {len(products)} prodotti")
        return
    seen = state[category]
    for pid, product in products.items():
        if pid in seen:
            continue
        send(f"Nuovo prodotto {category}\n\n{product['title'][:1000]}\n\n{product['url']}")
        seen[pid] = product
        persist()
        time.sleep(1.1)
    print(f"{category}: controllati {len(products)} prodotti")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Legge il sito senza inviare o salvare")
    parser.add_argument("--chat-id", action="store_true", help="Mostra le chat private che hanno scritto al bot")
    parser.add_argument("--test-message", action="store_true")
    parser.add_argument("--state", type=Path, default=Path("data/state.json"))
    args = parser.parse_args()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not args.dry_run and not token:
        raise ValueError("Impostare TELEGRAM_BOT_TOKEN")
    if args.chat_id:
        updates = telegram("getUpdates", {}, token)
        chats = {str(u["message"]["chat"]["id"]) for u in updates if u.get("message", {}).get("chat", {}).get("type") == "private"}
        print("Chat ID: " + ", ".join(sorted(chats)) if chats else "Apri il bot su Telegram, invia /start e riprova.")
        return
    if not args.dry_run and not chat:
        raise ValueError("Impostare TELEGRAM_CHAT_ID")
    send = lambda message: telegram("sendMessage", {"chat_id": chat, "text": message, "link_preview_options": {"is_disabled": True}}, token)
    if args.test_message:
        send("Bot Gametrade collegato: avvisi One Piece e Naruto.")
        return
    state = json.loads(args.state.read_text(encoding="utf-8")) if args.state.exists() else {}
    if not isinstance(state, dict) or any(not isinstance(v, dict) for v in state.values()):
        raise ValueError("Stato non valido: ripristinare il file, non cancellarlo")
    errors = []
    for category, url in CATEGORIES.items():
        try:
            products = collect(url)
            if args.dry_run:
                print(f"{category}: {len(products)} prodotti")
                for product in products.values():
                    print("  " + product["title"])
            else:
                update_category(state, category, products, send, lambda: save(args.state, state))
        except Exception as exc:
            print(f"ERRORE {category}: {type(exc).__name__}: {exc}")
            errors.append(category)
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
