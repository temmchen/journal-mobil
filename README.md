# 📱 Journal Mobil

Verschlüsselte iPhone-Fassung des **Journal de Classe** (Klassenbuch von Tom Bleyer, LTEtt): nur die
**Agenda** (Stundenplan, Ausnahmen, Ferien, alle Einträge des Schuljahres samt Dateien) und die
**Skripte** (PDF je Klasse und Modul). Gehostet kostenlos auf **GitHub Pages**, obwohl dieses
Repository öffentlich ist: sämtliche Inhalte liegen ausschließlich als **AES-256-GCM-Chiffrat** in
`docs/vaults/`. Entschlüsselt wird erst im Browser nach Eingabe des Passworts. Im Repo steht kein
Passwort und kein Klartext.

- Portal: https://temmchen.github.io/journal-mobil/
- Anleitung für den Alltag: `KI/Journal Mobil/README.md` in OneDrive (Knopf im Journal, Kachel im
  Dashboard, Doppelklick-Button, Portal-Wächter)

## Alltag

Inhalte werden im Journal de Classe gepflegt. Veröffentlichen — nur wenn sich etwas geändert hat:

```bash
python3 veroeffentlichen.py              # pull · prüfen · bauen · commit · push
python3 veroeffentlichen.py --pruefen    # nur nachsehen: NICHTS-ZU-TUN / OFFEN (Portal-Wächter)
python3 veroeffentlichen.py --erzwingen  # auch ohne Änderung (nach Passwort-/Code-Änderungen)
```

Der Portal-Wächter (`_Portal-Setup/portal-waechter.py`, launchd alle 20 min) ruft das für dieses und
die beiden anderen Portale automatisch auf.

## Zugänge

```bash
python3 verwaltung.py liste
python3 verwaltung.py passwort "Tom (iPhone)"    # neu würfeln, Tresor neu verschlüsseln
python3 verwaltung.py zugang "iPad"
python3 verwaltung.py entfernen "iPad"
python3 verwaltung.py readme                     # PASSWOERTER.md + QR-Code in OneDrive neu schreiben
```

`zugangsdaten.json` liegt **nur lokal** (Verknüpfung nach OneDrive `_Portal-Setup/geheim/`, gitignored).

## Technik

```
Journal-Mobil/
├── build.py                    liest KI/Journal de Classe/<Jahr>/ → verschlüsselt nach docs/vaults/
├── veroeffentlichen.py         Ein-Klick-Veröffentlichung, --pruefen für den Wächter
├── verwaltung.py               Zugänge, Passwörter, Passwort-Übersicht + QR
├── zugangsdaten.beispiel.json  Vorlage ohne echtes Passwort
└── docs/                       GitHub-Pages-Wurzel
    ├── index.html              Web-App: Anmeldung, Agenda, Skripte, PDF-Viewer (WebCrypto, pdf.js)
    ├── sw.js                   Service Worker: App-Hülle + Dateien offline
    ├── manifest.webmanifest, icons/
    ├── lib/                    pdf.js 4.10.38 (Apache 2.0), lokal
    └── vaults/                 index.json (Salts, eingewickelte Schlüssel) + <id>/m.enc + <id>/f/<id>.enc
```

Krypto: PBKDF2-HMAC-SHA256 (600 000 Iterationen, 16-B-Salt je Zugang) → AES-256-GCM; ein
Tresor-Schlüssel, je Datei eine Nonce; geänderte Dateien bekommen eine neue Zufalls-Kennung (deshalb darf
das iPhone Dateien dauerhaft zwischenspeichern). Inkrementeller Build über `.build-state.json`:
unveränderte Dateien behalten ihr Chiffrat byte-genau, die Git-Historie wächst nur um Neues.

Einmalige Voraussetzung auf einem neuen Mac: `pip3 install --user cryptography`, dann
`KI/Journal Mobil/Journal Mobil einrichten.command`.

Lokal testen: `cd docs && python3 -m http.server 8425 --bind 127.0.0.1` → http://127.0.0.1:8425/
(Direktes Öffnen der Datei per Doppelklick funktioniert nicht — `fetch()` und der Service Worker
brauchen http/https.)
