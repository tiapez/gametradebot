# Avvisi Gametrade su Telegram

Controlla le categorie pubbliche One Piece e Naruto ogni 30 minuti e invia nome e link dei nuovi prodotti, inclusi i preordini. Python 3.11 o successivo, nessuna libreria da installare.

Al primo controllo di ciascuna categoria memorizza i prodotti presenti senza inviarli. Per "nuovo" si intende un identificativo mai osservato dopo questo primo controllo: non monitora riassortimenti, prezzi o cambi di disponibilità. I consigli in fondo alla pagina sono esclusi. Nessun account Gametrade richiesto; prodotti visibili soltanto dopo il login non sono coperti.

## 1. Crea il bot Telegram

1. Apri [BotFather](https://t.me/BotFather), invia `/newbot` e scegli nome e username.
2. Conserva il token ricevuto: non inserirlo nel codice o nel repository.
3. Apri la chat del tuo nuovo bot e premi **Avvia** o invia `/start`.
4. Nel terminale PowerShell, dalla cartella del progetto, inserisci il token senza mostrarlo né salvarlo nella cronologia:

```powershell
$botSecret = Read-Host 'Token BotFather' -AsSecureString
$env:TELEGRAM_BOT_TOKEN = [System.Net.NetworkCredential]::new('', $botSecret).Password
python monitor.py --chat-id
```

Annota il Chat ID restituito. Se appaiono più ID, invia un messaggio riconoscibile al bot e verifica la chat corretta prima di configurare il destinatario. Questa procedura è pensata per un bot nuovo, senza webhook o altri programmi che leggono i suoi messaggi.

## 2. Attiva online con GitHub Actions

1. Crea un repository **pubblico** su GitHub e carica `monitor.py`, `tests/`, `.gitignore` e `.github/workflows/monitor.yml`, mantenendo le cartelle. Non caricare le copie HTML locali o credenziali. Puoi usare GitHub Desktop per includere facilmente la cartella `.github`.
2. In **Settings → Secrets and variables → Actions → New repository secret**, crea:
   - `TELEGRAM_BOT_TOKEN`: il token di BotFather.
   - `TELEGRAM_CHAT_ID`: il tuo Chat ID.
3. In **Settings → Actions → General**, consenti al workflow di leggere e scrivere il repository. Le regole di protezione del branch devono permettere al bot di salvare `data/state.json`.
4. In **Actions → Controlla Gametrade → Run workflow**, avvia la prima esecuzione sul branch predefinito. Deve terminare verde e creare `data/state.json`.
5. Da quel momento il controllo è programmato ai minuti 17 e 47 di ogni ora. Non serve tenere acceso il PC.

Il file `data/state.json` viene creato **alla prima esecuzione online**, senza precompilare il catalogo durante lo sviluppo. Contiene solo identificativi, titoli e link pubblici. Non cancellarlo: è la memoria del bot. Non avviare due copie locali sullo stesso file e non usare copie locali e online per la stessa chat, altrimenti potresti ricevere duplicati.

Per provare subito l'invio dal PC:

```powershell
$env:TELEGRAM_CHAT_ID = 'INSERISCI_IL_TUO_CHAT_ID'
python monitor.py --test-message
```

## Verifiche e uso locale

```powershell
python -m unittest discover -s tests -v
python monitor.py --dry-run
python monitor.py
```

`--dry-run` legge il sito senza inviare messaggi e senza salvare lo stato. L'esecuzione normale effettua un singolo controllo; online la ripetizione è gestita da GitHub Actions.

## Comandi nella chat Telegram

Le schede di `/prodotti`, `/prenotazioni` e gli avvisi di nuovi prodotti includono immagine, nome e data di uscita (quando indicata sul sito), oltre a stato e link. La data di uscita è distinta dalla scadenza del preordine. Se manca la data compare "Non indicata sul sito"; se manca la foto o Telegram la rifiuta, viene inviato il testo. I vecchi dati si arricchiscono al successivo controllo normale: dopo un aggiornamento locale, chiudi l'ascolto con Ctrl+C, esegui `python monitor.py` e riavvia `python monitor.py --listen`. `/prenotazioni` legge subito i dati aggiornati dal sito.

Dopo aver configurato token e Chat ID nella stessa finestra PowerShell:

```powershell
python monitor.py
python monitor.py --listen
```

Il primo comando aggiorna il database, il secondo resta in ascolto (Ctrl+C per uscire). Nella chat del bot scrivi:

- `/prodotti`: elenco dei prodotti nel database locale, con stato rilevato all'ultimo controllo. Include lo storico e distingue quelli non più presenti. Per i vecchi dati senza stato di prenotazione, esegui un controllo per aggiornarli.
- `/prenotazioni`: rilegge le due categorie e invia solo i prodotti contrassegnati PRE-ORDER sul sito in quel momento. Non modifica la memoria delle notifiche. Un preordine sul sito non certifica un ordine o una prenotazione effettuata dal tuo account.
- `/aiuto`: riepilogo dei comandi.

Le risposte arrivano solo alla chat configurata. `--listen` gestisce le richieste ma non esegue controlli automatici del catalogo: `/prenotazioni` legge sempre il sito, `/prodotti` legge il file locale. Non usare contemporaneamente l'ascolto locale e Actions sullo stesso bot: sospendi il workflow durante le prove locali, quindi riattivalo dopo aver chiuso l'ascolto. Le due copie hanno database separati.

Online il workflow gestisce i comandi ogni 30 minuti, con possibili ritardi di GitHub; non è una risposta istantanea. `python monitor.py --commands` gestisce le richieste in attesa una sola volta. Il file `data/telegram_offset.json` memorizza l'ultima richiesta elaborata, senza contenuti delle chat o credenziali. Non cancellarlo. Telegram conserva le richieste in attesa per un tempo limitato; non lasciare il bot inattivo per giorni se vuoi ricevere risposta ai comandi. Un errore dopo una risposta ma prima del salvataggio può far ripetere la risposta al tentativo successivo.

## Costi e limiti

- GitHub Actions è gratuito sui repository pubblici con runner standard. I repository privati hanno quote: non presumere che qualsiasi frequenza sia gratuita. [Prezzi ufficiali](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
- L'orario non è garantito: i controlli programmati possono essere ritardati o saltati. Nei repository pubblici GitHub disabilita i workflow programmati dopo 60 giorni senza attività del repository: verifica periodicamente la sezione Actions e riattivali se necessario. [Documentazione schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
- Se il sito cambia struttura, blocca le richieste o restituisce un catalogo incompleto, il controllo fallisce senza cancellare la memoria. L'altra categoria viene comunque controllata. Abilita le notifiche GitHub per i workflow falliti: gli errori non generano avvisi Telegram.
- Lo stato viene salvato dopo ciascun invio riuscito e pubblicato anche dopo errori parziali. Un arresto fra invio e salvataggio, un timeout ambiguo di Telegram o un errore nel salvataggio su GitHub possono produrre un avviso duplicato; la consegna esattamente una volta non è garantita.
- La paginazione segue collegamenti della stessa categoria e verifica il totale. Se Gametrade introducesse una paginazione JavaScript diversa, servirà aggiornare il lettore.

Riferimento Telegram: [creazione bot](https://core.telegram.org/bots/tutorial), [API](https://core.telegram.org/bots/api).
