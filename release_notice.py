"""Notifica una tantum per gli aggiornamenti distribuiti del bot."""
import json
from pathlib import Path

RELEASE_ID = '2026-10-25-events-and-reminders-v1'
MESSAGE = """🟢 Bot aggiornato e riavviato

Novità disponibili:
• /londra26-27 — calendario e promemoria registrazioni London 26-27
• /event — elenco degli eventi ONE PIECE CARD GAME attivi
• /op18pre — stato delle iscrizioni OP-18

Ora controllo automaticamente:
• nuovi prodotti One Piece e Naruto su Gametrade
• eventi One Piece nuovi o aggiornati
• modifiche alla pagina London 26-27
• modifiche alla pagina OP-18

Promemoria OP-18 previsto il 5 novembre 2026, al primo controllo dopo mezzanotte italiana. La pagina ufficiale indica l'apertura il 6 novembre, ma non specifica ancora l'orario.

I controlli vengono eseguiti ogni 30 minuti circa. Non devi fare nulla."""


def enqueue_once(path, subscribers, message_type, save):
    path = Path(path)
    state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'sent': []}
    sent = state.setdefault('sent', [])
    if RELEASE_ID in sent:
        return False
    message = message_type(MESSAGE)
    message.key = 'release:' + RELEASE_ID
    subscribers.enqueue(message)
    sent.append(RELEASE_ID)
    save(path, state)
    return True
