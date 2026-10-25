# Avvisi Gametrade su Telegram

Controlla le categorie pubbliche One Piece e Naruto ogni 30 minuti e invia nome, data di uscita e immagine dei nuovi prodotti, inclusi i preordini. Supporta più iscritti, ognuno nella propria chat privata. Richiede Python 3.11 o successivo e `python -m pip install -r requirements.txt`.

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

1. Crea un repository **pubblico** su GitHub e carica `monitor.py`, `requirements.txt`, `tests/`, `.gitignore` e `.github/workflows/monitor.yml`, mantenendo le cartelle. Non caricare le copie HTML locali o credenziali. Puoi usare GitHub Desktop per includere facilmente la cartella `.github`.
2. In **Settings → Secrets and variables → Actions → New repository secret**, crea:
   - `TELEGRAM_BOT_TOKEN`: il token di BotFather.
   - `TELEGRAM_CHAT_ID`: il tuo Chat ID (facoltativo: ti iscrive automaticamente soltanto alla creazione dell'archivio; serve anche al messaggio di prova).
   - `SUBSCRIBERS_KEY`: chiave per cifrare le iscrizioni, obbligatoria online. Generala sul tuo PC con il comando sotto, copiala nel secret e conservala. Non pubblicarla e non cambiarla senza migrare l'archivio cifrato esistente.
3. In **Settings → Actions → General**, consenti al workflow di leggere e scrivere il repository. Le regole di protezione del branch devono permettere al bot di salvare `data/state.json`.
4. In **Actions → Controlla Gametrade → Run workflow**, avvia la prima esecuzione sul branch predefinito. Deve terminare verde e creare `data/state.json`.
5. Da quel momento il controllo è programmato ai minuti 17 e 47 di ogni ora. Non serve tenere acceso il PC.

Generazione della chiave (il comando stampa una nuova chiave privata, da copiare solo nei segreti GitHub):

```powershell
python -m pip install -r requirements.txt
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Se esiste già `data/subscribers.enc` online, devi mantenere la chiave che lo ha creato. In locale, senza variabile `SUBSCRIBERS_KEY`, viene generato automaticamente `data/subscribers.key`, escluso da Git. Per trasferire iscrizioni locali online usa quella stessa chiave nel secret e trasferisci soltanto l'archivio `.enc`; non sovrascrivere un archivio online esistente con una copia locale diversa.

Le iscrizioni e gli avvisi in attesa sono salvati in `data/subscribers.enc`, cifrato con [Fernet](https://cryptography.io/en/latest/fernet/). Gli ID delle chat non sono pubblicati in chiaro. Il bot conserva solo ID e messaggi ancora da consegnare, senza nomi, username o cronologia delle conversazioni. `/stop` cancella l'iscrizione e gli avvisi in coda dall'archivio corrente; le vecchie versioni cifrate rimangono nella cronologia Git. La chiave non va caricata nel repository. Se manca in Actions, il controllo si interrompe prima di inviare o modificare lo stato.

Il file `data/state.json` viene creato **alla prima esecuzione online**, senza precompilare il catalogo durante lo sviluppo. Contiene solo identificativi, titoli e link pubblici. Non cancellarlo: è la memoria del bot. Non avviare due copie locali sullo stesso file e non usare copie locali e online per la stessa chat, altrimenti potresti ricevere duplicati.

Per provare subito l'invio dal PC:

```powershell
$env:TELEGRAM_CHAT_ID = 'INSERISCI_IL_TUO_CHAT_ID'
python monitor.py --test-message
```

## Verifiche e uso locale

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python monitor.py --dry-run
python monitor.py
```

`--dry-run` legge il sito senza inviare messaggi e senza salvare lo stato. L'esecuzione normale effettua un singolo controllo; online la ripetizione è gestita da GitHub Actions.

## Comandi nella chat Telegram

Le schede di `/prodotti`, `/prenotazioni` e gli avvisi di nuovi prodotti includono immagine, nome e data di uscita (quando indicata sul sito), oltre allo stato, senza link. La data di uscita è distinta dalla scadenza del preordine. Se manca la data compare "Non indicata sul sito"; se manca la foto o Telegram la rifiuta, viene inviato il testo. I vecchi dati si arricchiscono al successivo controllo normale: dopo un aggiornamento locale, chiudi l'ascolto con Ctrl+C, esegui `python monitor.py` e riavvia `python monitor.py --listen`. `/prenotazioni` legge subito i dati aggiornati dal sito.

Dopo aver configurato token e Chat ID nella stessa finestra PowerShell:

```powershell
python monitor.py
python monitor.py --listen
```

Il primo comando aggiorna il database, il secondo resta in ascolto (Ctrl+C per uscire). Nella chat del bot scrivi:

- `/prodotti`: elenco dei prodotti nel database locale, con stato rilevato all'ultimo controllo. Include lo storico e distingue quelli non più presenti. Per i vecchi dati senza stato di prenotazione, esegui un controllo per aggiornarli.
- `/prenotazioni`: rilegge le due categorie e invia solo i prodotti contrassegnati PRE-ORDER sul sito in quel momento. Non modifica la memoria delle notifiche. Un preordine sul sito non certifica un ordine o una prenotazione effettuata dal tuo account.
- `/aiuto`: riepilogo dei comandi.
- `/start`: iscrive la propria chat privata agli avvisi One Piece e Naruto; ripeterlo non crea duplicati.
- `/stop`: cancella l'iscrizione e gli avvisi ancora in attesa. Vale anche per il proprietario.

Condividi con gli amici il link Telegram del bot: ciascuno preme Avvia o scrive `/start`. Le risposte arrivano nella chat di chi le richiede e le novità vengono inviate a tutti gli iscritti. Le chat di gruppo sono ignorate. Chi non è iscritto può usare `/aiuto`, `/start` e `/stop`; gli altri comandi richiedono prima `/start`. I nuovi iscritti non ricevono automaticamente lo storico: possono consultarlo con `/prodotti`.

`--listen` gestisce le richieste ma non esegue controlli automatici del catalogo: `/prenotazioni` legge sempre il sito, `/prodotti` legge il file locale. Non usare contemporaneamente l'ascolto locale e Actions sullo stesso bot: sospendi il workflow durante le prove locali, quindi riattivalo dopo aver chiuso l'ascolto. Le due copie hanno database e iscrizioni separati. Per un controllo locale completo, esegui prima `python monitor.py --commands` e poi `python monitor.py`, così vengono elaborate le disiscrizioni prima degli avvisi.

Online il workflow gestisce i comandi ogni 30 minuti, con possibili ritardi di GitHub; non è una risposta istantanea. `python monitor.py --commands` gestisce le richieste in attesa una sola volta. Il file `data/telegram_offset.json` memorizza l'ultima richiesta elaborata, senza contenuti delle chat o credenziali. Non cancellarlo. Telegram conserva le richieste in attesa per un tempo limitato; non lasciare il bot inattivo per giorni se vuoi ricevere risposta ai comandi. Un errore dopo una risposta ma prima del salvataggio può far ripetere la risposta al tentativo successivo.

## Bandai London: promemoria e cambiamenti della pagina

Il controllo normale include anche la [pagina Pre-Registration London 26-27](https://www.bandaicardgames-fest.com/26-27/en/london/news/london-pre-registrationd.html). Tutti gli iscritti ricevono:

- Un promemoria 24 ore prima di ciascuna apertura con data e ora nella sezione "Registration Dates, Links". Viene spedito al primo controllo utile: con Actions può arrivare dopo l'orario previsto. Se un controllo viene saltato, viene recuperato solo prima dell'apertura, mai dopo.
- Un avviso quando cambiano testo, link o riferimenti alle immagini dell'articolo, con un riepilogo prima/dopo e il link ufficiale. Menu, footer, script e differenze di soli spazi sono esclusi. Non rileva immagini sostituite mantenendo lo stesso URL.

Il primo controllo salva il riferimento senza notificare una modifica. Le date vengono rilette e aggiornate automaticamente; un cambiamento non riconosciuto sospende i promemoria e invia un avviso. Un errore di rete non viene scambiato per una modifica. Gli avvisi di cambiamento e il calendario contengono il link alla fonte; le schede prodotto restano senza link.

Sono monitorate le aperture delle registrazioni con orario esplicito, non le giornate dei tornei prive di orario. Gli anni impliciti si riferiscono a questa edizione: ottobre 2026 e gennaio 2027. GMT/BST vengono convertiti in Europe/Rome. Non si tratta di un controllo della disponibilità su Weeztix.

Comando Telegram: `/londra26-27` mostra il calendario salvato. È supportata anche la variante `/londra26_27`, utile nei client Telegram che non riconoscono il trattino come parte di un comando. Il vecchio `/bandai` è stato rimosso e viene trattato come comando sconosciuto. In locale, `python monitor.py --bandai-dry-run` legge e stampa le date senza inviare messaggi o modificare dati. `--listen` risponde ai comandi ma, come prima, non esegue il monitoraggio programmato: per controllare pagina e promemoria usa `python monitor.py`. Su Actions tutto è incluso nel controllo ogni 30 minuti, senza nuovi segreti.

La memoria è `data/bandai.json`, salvata dal workflow insieme al catalogo. Non cancellarla per evitare nuovi avvisi su eventi già segnalati. Le consegne in attesa rimangono cifrate nell'archivio iscritti. Chi si iscrive dopo l'invio di un promemoria può consultare `/londra26-27`; non riceve automaticamente i promemoria già inviati. `/stop` interrompe anche gli avvisi London.

## Eventi ONE PIECE CARD GAME

Il bot controlla anche la [pagina ufficiale degli eventi](https://en.onepiece-cardgame.com/events/) ogni 30 minuti circa. Considera attive le schede pubblicate nella pagina principale, escludendo la sezione separata “Past Events”. Al primo controllo salva la base senza inviare decine di avvisi; in seguito avvisa tutti gli iscritti quando compare una nuova scheda o quando cambia nome, periodo, categoria, regolamento, descrizione, immagine o collegamento di un evento esistente.

Il comando `/event` (anche `/events`) elenca tutte le schede attive rilevate nell'ultimo controllo, dividendole in più messaggi quando necessario. Ogni voce include nome, periodo, categoria, eventuale regolamento e descrizione, oltre al collegamento ufficiale. Gli eventi rimossi dalla pagina non generano un avviso, perché la richiesta riguarda eventi nuovi o aggiornati; spariscono però dall'elenco `/event` dopo il controllo successivo.

La memoria è `data/op_events.json` e viene salvata automaticamente da Actions. Una risposta incompleta o una modifica non riconosciuta della pagina interrompe quel controllo senza sostituire la base precedente, evitando falsi avvisi. Modifiche esterne alle schede, come menu e footer, sono ignorate. `/stop` interrompe anche questi avvisi. Non servono nuovi segreti GitHub.

## Pre-iscrizione evento OP-18

Il bot controlla ogni 30 minuti anche la pagina ufficiale [4th Anniversary Event (OP-18 Release Event)](https://en.onepiece-cardgame.com/events/store-tournament-op18.html). Al primo controllo salva il contenuto principale senza inviare un avviso; dai controlli successivi segnala agli iscritti modifiche a testi, collegamenti o riferimenti alle immagini, mostrando un riepilogo prima/dopo e il collegamento ufficiale.

Il comando `/op18pre` mostra la data di apertura delle iscrizioni giocatori, il collegamento TCG+ e l'ora dell'ultimo controllo. Attualmente la pagina indica **6 novembre 2026**, senza un orario. In assenza di un orario ufficiale, il promemoria entra in coda dalla mezzanotte italiana del giorno precedente e viene inviato al primo controllo utile del **5 novembre 2026**. Non viene inviato dopo l'apertura.

Se la data cambia, il calendario e l'eventuale promemoria ancora in attesa vengono aggiornati automaticamente. Se il formato diventa illeggibile, il bot sospende quel promemoria e invia un avviso invece di usare una data vecchia. La memoria è `data/op18.json`; non servono nuovi segreti GitHub. `/stop` interrompe anche questi avvisi.

## Costi e limiti del servizio

- GitHub Actions è gratuito sui repository pubblici con runner standard. I repository privati hanno quote: non presumere che qualsiasi frequenza sia gratuita. [Prezzi ufficiali](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
- L'orario non è garantito: i controlli programmati possono essere ritardati o saltati. Nei repository pubblici GitHub disabilita i workflow programmati dopo 60 giorni senza attività del repository: verifica periodicamente la sezione Actions e riattivali se necessario. [Documentazione schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
- Se il sito cambia struttura, blocca le richieste o restituisce un catalogo incompleto, il controllo fallisce senza cancellare la memoria. L'altra categoria viene comunque controllata. Abilita le notifiche GitHub per i workflow falliti: gli errori non generano avvisi Telegram.
- Le novità sono messe in coda per ciascun iscritto prima di aggiornare il catalogo. Ogni consegna riuscita viene rimossa dalla sua coda; gli errori temporanei vengono ritentati al controllo successivo senza reinviare agli altri destinatari. Chi blocca il bot viene disiscritto. Un arresto fra invio e salvataggio, un timeout ambiguo di Telegram o un errore nel salvataggio su GitHub possono produrre un avviso duplicato; la consegna esattamente una volta non è garantita.
- La paginazione segue collegamenti della stessa categoria e verifica il totale. Se Gametrade introducesse una paginazione JavaScript diversa, servirà aggiornare il lettore.

Riferimento Telegram: [creazione bot](https://core.telegram.org/bots/tutorial), [API](https://core.telegram.org/bots/api).
