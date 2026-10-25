"""Gametrade e Bandai London -> Telegram. Dipendenze in requirements.txt."""
import argparse
import json
import os
import re
import time
import urllib.request
import urllib.error
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from cryptography.fernet import Fernet
from datetime import datetime, timezone
import bandai
import op_events
import op18
import release_notice

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
        self.preorder = None
        self.card_depth = None
        self.card = {}
        self.date_part = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if tag == "div":
            marker = attrs.get("id") == "listaarticoli"
            self.found_catalog |= marker
            self.divs.append("catalog" if marker else "title" if "product-title" in classes else "pages" if "pagination" in classes else "")
            if "catalog" in self.divs and "product-card" in classes:
                self.preorder = "PRE-ORDER" in classes
                self.card_depth = len(self.divs)
                self.card = {"image_url": None, "release_month": "", "release_day": ""}
        if self.card_depth is not None:
            if tag == "img" and not self.card.get("image_url"):
                image = urljoin(BASE, attrs.get("src", ""))
                if urlsplit(image).scheme == "https" and urlsplit(image).hostname in ("www.gametrade.it", "www.lafumetteria.it"):
                    self.card["image_url"] = image
            if tag == "span":
                self.date_part = "release_month" if "meseanno" in classes else "release_day" if "from_day" in classes else None
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
        if self.date_part:
            self.card[self.date_part] += data

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            pid, url, parts = self.current
            title = " ".join("".join(parts).split())
            if title:
                self.products[pid] = self.card.copy()
                self.products[pid].update(title=title, url=url, preorder=self.preorder)
            self.current = None
        if tag == "span":
            self.in_summary = False
            self.date_part = None
        if tag == "div" and self.divs:
            if len(self.divs) == self.card_depth:
                self.preorder = None
                self.card_depth = None
                self.card = {}
                self.date_part = None
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
                raise RuntimeError("Impossibile leggere la pagina monitorata") from None
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


class TelegramRejected(RuntimeError):
    def __init__(self, code):
        super().__init__("Telegram ha rifiutato la richiesta")
        self.code = code


def telegram(method, payload, token):
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise TelegramRejected(exc.code) from None
    except (OSError, ValueError):
        # Non stampare eccezioni urllib: l'URL contiene il token.
        raise RuntimeError("Telegram non raggiungibile o credenziali non valide") from None
    if not result.get("ok"):
        raise TelegramRejected(result.get("error_code"))
    return result["result"]


class ProductMessage(str):
    """Text plus optional photo, shared by alerts and catalog commands."""
    def __new__(cls, text, image_url=None):
        message = super().__new__(cls, text)
        message.image_url = image_url
        return message


def release_date(product):
    month = " ".join(product.get("release_month", "").split())
    day = " ".join(product.get("release_day", "").split())
    months = dict(zip("January February March April May June July August September October November December".split(),
                      "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split()))
    for english, italian in months.items():
        month = re.sub(r"\b" + english + r"\b", italian, month, flags=re.I)
    return " ".join(filter(None, [day, month])) if month else "Non indicata sul sito"


def product_message(product, detail=""):
    text = f"{product['title'][:1000]}\nData uscita: {release_date(product)}"
    if detail:
        text += f"\n{detail}"
    if not product.get("image_url"):
        text += "\nImmagine non disponibile"
    return ProductMessage(text, product.get("image_url"))


def send_message(message, token, chat, api=telegram):
    image = getattr(message, "image_url", None)
    if image:
        # Telegram captions have a smaller limit than ordinary messages.
        short = len(message.encode("utf-16-le")) // 2 <= 1024
        payload = {"chat_id": chat, "photo": image}
        if short:
            payload["caption"] = str(message)
        try:
            api("sendPhoto", payload, token)
        except TelegramRejected as exc:
            if exc.code != 400:
                raise
            message = str(message) + "\nImmagine non disponibile su Telegram."
        else:
            if short:
                return
            time.sleep(1.1)
    api("sendMessage", {"chat_id": chat, "text": str(message),
                        "link_preview_options": {"is_disabled": True}}, token)


def save(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class Subscribers:
    """Encrypted subscription list and per-recipient delivery queue."""
    def __init__(self, path, owner="", key=None):
        self.path = Path(path)
        key = key or os.environ.get("SUBSCRIBERS_KEY")
        if not key:
            if os.environ.get("GITHUB_ACTIONS"):
                raise ValueError("Configurare il secret SUBSCRIBERS_KEY prima di avviare Actions")
            key_path = self.path.with_suffix(".key")
            if not key_path.exists():
                if self.path.exists():
                    raise ValueError("Chiave iscrizioni mancante: ripristinarla prima di continuare")
                key_path.parent.mkdir(parents=True, exist_ok=True)
                key_path.write_bytes(Fernet.generate_key())
            key = key_path.read_bytes()
        self.cipher = Fernet(key)
        if self.path.exists():
            try:
                self.users = json.loads(self.cipher.decrypt(self.path.read_bytes()))
                if not isinstance(self.users, dict) or any(not isinstance(v, dict) for v in self.users.values()):
                    raise ValueError()
            except Exception:
                raise ValueError("Archivio iscrizioni non leggibile: verificare SUBSCRIBERS_KEY") from None
        else:
            self.users = {str(owner): {}} if owner else {}
            self.persist()

    def persist(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(self.cipher.encrypt(json.dumps(self.users).encode()))
        temporary.replace(self.path)

    def subscribe(self, chat):
        self.users.setdefault(str(chat), {})
        self.persist()

    def unsubscribe(self, chat):
        self.users.pop(str(chat), None)
        self.persist()

    def enqueue(self, message):
        for pending in self.users.values():
            pending.setdefault(message.key, {"text": str(message), "image": message.image_url,
                                             "expires_at": getattr(message, 'expires_at', None)})
        self.persist()

    def prune_bandai_reminders(self, valid_keys):
        changed = False
        for pending in self.users.values():
            for key in list(pending):
                if key.startswith('bandai:reminder:') and key not in valid_keys:
                    del pending[key]
                    changed = True
        if changed:
            self.persist()

    def prune_pending(self, prefix, valid_keys):
        changed = False
        for pending in self.users.values():
            for key in list(pending):
                if key.startswith(prefix) and key not in valid_keys:
                    del pending[key]
                    changed = True
        if changed:
            self.persist()

    def deliver(self, token, api=telegram):
        failed = False
        for chat in list(self.users):
            for key, item in list(self.users[chat].items()):
                if item.get('expires_at') and datetime.fromisoformat(item['expires_at']) <= datetime.now(timezone.utc):
                    del self.users[chat][key]
                    self.persist()
                    continue
                try:
                    send_message(ProductMessage(item["text"], item["image"]), token, chat, api)
                except TelegramRejected as exc:
                    if exc.code == 403:
                        self.unsubscribe(chat)
                    else:
                        failed = True
                    break
                except RuntimeError:
                    failed = True
                    break
                del self.users[chat][key]
                self.persist()
                time.sleep(1.1)
        if failed:
            raise RuntimeError("Alcuni avvisi non consegnati: conservati per il prossimo tentativo")


def update_category(state, category, products, send, persist):
    if category not in state:
        state[category] = products.copy()
        persist()
        print(f"{category}: inizializzati {len(products)} prodotti")
        return
    seen = state[category]
    for pid, product in seen.items():
        product["present"] = pid in products
    persist()
    for pid, product in products.items():
        if pid in seen:
            seen[pid] = dict(product, present=True)
            persist()
            continue
        message = product_message(product, f"Nuovo prodotto {category}")
        message.key = f"{category}:{pid}"
        send(message)
        seen[pid] = product
        persist()
        time.sleep(1.1)
    print(f"{category}: controllati {len(products)} prodotti")


def product_messages(catalog, preorders=False, categories=None):
    """One bounded message per product; never silently truncate a catalog."""
    for category in CATEGORIES if categories is None else categories:
        if category not in catalog:
            yield f"{category}: database non ancora inizializzato. Esegui prima un controllo."
            continue
        items = [(pid, p) for pid, p in catalog[category].items()
                 if not preorders or p.get("preorder") is True]
        label = "in prenotazione sul sito ora" if preorders else "nel database (ultimo controllo)"
        yield f"{category}: {len(items)} prodotti {label}."
        for pid, p in items:
            if p.get("present") is False:
                status = "Non presente all'ultimo controllo"
            elif p.get("preorder") is True:
                status = "In prenotazione"
            elif p.get("preorder") is False:
                status = "Non indicato come preordine"
            else:
                status = "Stato prenotazione non ancora rilevato"
            text = product_message(p, f"{category} · {status}")
            if len(text) > 3500:
                raise ValueError("Scheda prodotto troppo lunga per Telegram")
            yield text


HELP = ("Comandi Gametrade:\n/prodotti - prodotti nel database, incluso lo storico\n"
        "/prenotazioni - preordini attuali riletti dal sito\n/start - attiva avvisi\n"
        "/londra26-27 - calendario aperture registrazioni London\n"
        "/event - tutti gli eventi One Piece attivi\n"
        "/op18pre - stato iscrizioni evento OP-18\n"
        "/stop - disattiva avvisi e cancella l'iscrizione\n/aiuto - questo messaggio")


def process_commands(state_path, offset_path, token, chat, api=telegram, fetch_catalog=collect,
                     subscribers=None, bandai_path=None, events_path=None, op18_path=None):
    subscribers = subscribers or Subscribers(state_path.parent / "subscribers.enc", chat)
    offset = json.loads(offset_path.read_text(encoding="utf-8")) if offset_path.exists() else 0
    updates = api("getUpdates", {"offset": offset, "timeout": 0, "allowed_updates": ["message"]}, token)

    def reply(text):
        try:
            send_message(text, token, destination, api)
        except TelegramRejected as exc:
            if exc.code != 403:
                raise
            subscribers.unsubscribe(destination)
        time.sleep(1.1)

    for update in updates:
        message = update.get("message", {})
        destination = str(message.get("chat", {}).get("id", ""))
        if message.get("chat", {}).get("type") == "private" and destination:
            text = message.get("text", "").strip()
            command = text.split()[0].split("@")[0].lower() if text else ""
            if command == "/start":
                subscribers.subscribe(destination)
                reply("Iscrizione attiva! Riceverai le novita One Piece e Naruto, i promemoria London e OP-18 e gli avvisi su eventi One Piece nuovi o aggiornati.\n"
                      "Conserviamo il tuo ID chat cifrato per inviarti gli avvisi. /stop per cancellare l'iscrizione.\n"
                      "Su GitHub Actions rispondiamo al prossimo controllo (circa 30 minuti).\n\n" + HELP)
            elif command == "/stop":
                subscribers.unsubscribe(destination)
                reply("Iscrizione cancellata. Non riceverai altri avvisi. /start per riattivarli.")
            elif command in ("/help", "/aiuto"):
                reply(HELP)
            elif destination not in subscribers.users:
                if command.startswith("/"):
                    reply("Invia /start per attivare il bot nella tua chat privata.")
            elif command in ("/londra26-27", "/londra26_27"):
                reply(bandai.calendar_text(bandai_path or state_path.parent / 'bandai.json'))
            elif command in ("/event", "/events"):
                for event_text in op_events.active_messages(events_path or state_path.parent / 'op_events.json'):
                    reply(event_text)
            elif command == "/op18pre":
                reply(op18.status_text(op18_path or state_path.parent / 'op18.json'))
            elif command == "/prodotti":
                state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
                for text in product_messages(state):
                    reply(text)
            elif command == "/prenotazioni":
                # Read live without marking new items as already notified.
                for category, url in CATEGORIES.items():
                    try:
                        products = fetch_catalog(url)
                    except Exception:
                        reply(f"{category}: impossibile verificare le prenotazioni ora. Riprova piu tardi.")
                        continue
                    for text in product_messages({category: products}, preorders=True, categories=[category]):
                        reply(text)
            elif command.startswith("/"):
                reply("Comando non riconosciuto.\n" + HELP)
        offset = update["update_id"] + 1
        save(offset_path, offset)


def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="Legge il sito senza inviare o salvare")
    modes.add_argument("--chat-id", action="store_true", help="Mostra le chat private che hanno scritto al bot")
    modes.add_argument("--test-message", action="store_true")
    modes.add_argument("--listen", action="store_true", help="Risponde ai comandi Telegram fino a Ctrl+C")
    modes.add_argument("--commands", action="store_true", help="Legge e gestisce i comandi Telegram una volta")
    modes.add_argument("--bandai-dry-run", action="store_true", help="Mostra orari Bandai senza inviare o salvare")
    parser.add_argument("--state", type=Path, default=Path("data/state.json"))
    parser.add_argument("--offset", type=Path, default=Path("data/telegram_offset.json"))
    parser.add_argument("--subscribers", type=Path, default=Path("data/subscribers.enc"))
    parser.add_argument("--bandai-state", type=Path, default=Path("data/bandai.json"))
    parser.add_argument("--events-state", type=Path, default=Path("data/op_events.json"))
    parser.add_argument("--op18-state", type=Path, default=Path("data/op18.json"))
    parser.add_argument("--release-state", type=Path, default=Path("data/releases.json"))
    args = parser.parse_args()
    if args.bandai_dry_run:
        for event in bandai.extract_events(bandai.parse_article(download(bandai.URL))):
            print(bandai.event_line(event))
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not args.dry_run and not token:
        raise ValueError("Impostare TELEGRAM_BOT_TOKEN")
    if args.chat_id:
        updates = telegram("getUpdates", {}, token)
        chats = {str(u["message"]["chat"]["id"]) for u in updates if u.get("message", {}).get("chat", {}).get("type") == "private"}
        print("Chat ID: " + ", ".join(sorted(chats)) if chats else "Apri il bot su Telegram, invia /start e riprova.")
        return
    if args.test_message and not chat:
        raise ValueError("Impostare TELEGRAM_CHAT_ID")
    send = lambda message: send_message(message, token, chat)
    if args.test_message:
        send("Bot Gametrade collegato: avvisi One Piece e Naruto.")
        return
    subscribers = None if args.dry_run else Subscribers(args.subscribers, chat)
    if args.commands or args.listen:
        if args.commands:
            process_commands(args.state, args.offset, token, chat, subscribers=subscribers,
                             bandai_path=args.bandai_state, events_path=args.events_state,
                             op18_path=args.op18_state)
            return
        print("In ascolto: /prodotti, /prenotazioni, /aiuto. Ctrl+C per uscire.", flush=True)
        try:
            while True:
                try:
                    process_commands(args.state, args.offset, token, chat, subscribers=subscribers,
                                     bandai_path=args.bandai_state, events_path=args.events_state,
                                     op18_path=args.op18_state)
                except Exception as exc:
                    print(f"Errore comandi: {type(exc).__name__}. Nuovo tentativo tra 10 secondi.", flush=True)
                time.sleep(10)
        except KeyboardInterrupt:
            print("Ascolto terminato.")
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
                update_category(state, category, products, subscribers.enqueue, lambda: save(args.state, state))
        except Exception as exc:
            print(f"ERRORE {category}: {type(exc).__name__}: {exc}")
            errors.append(category)
    if subscribers is not None:
        try:
            bandai.run_check(args.bandai_state, download, subscribers, ProductMessage, save)
        except Exception as exc:
            print(f"ERRORE Bandai: {type(exc).__name__}: {exc}")
            errors.append('Bandai')
        try:
            op_events.run_check(args.events_state, download, subscribers, ProductMessage, save)
        except Exception as exc:
            print(f"ERRORE eventi One Piece: {type(exc).__name__}: {exc}")
            errors.append('eventi One Piece')
        try:
            op18.run_check(args.op18_state, download, subscribers, ProductMessage, save)
        except Exception as exc:
            print(f"ERRORE OP-18: {type(exc).__name__}: {exc}")
            errors.append('OP-18')
        try:
            release_notice.enqueue_once(args.release_state, subscribers, ProductMessage, save)
        except Exception as exc:
            print(f"ERRORE notifica aggiornamento: {type(exc).__name__}: {exc}")
            errors.append('notifica aggiornamento')
        try:
            subscribers.deliver(token)
        except RuntimeError as exc:
            print(str(exc))
            errors.append("consegna")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
