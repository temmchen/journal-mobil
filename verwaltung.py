#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verwaltung.py — Journal Mobil · Zugänge verwalten
==================================================

Verwaltet die Zugänge in zugangsdaten.json (liegt als Verknüpfung in OneDrive,
_Portal-Setup/geheim/Mobil-zugangsdaten.json) und schreibt die lesbaren
Passwort-Übersichten samt QR-Code in den OneDrive-Ordner „KI/Journal Mobil“.

    python3 verwaltung.py liste                 alle Zugänge anzeigen
    python3 verwaltung.py passwort "Tom (iPhone)"   Passwort neu würfeln + Tresor neu verschlüsseln
    python3 verwaltung.py zugang "iPad"         weiteren Zugang anlegen
    python3 verwaltung.py entfernen "iPad"      Zugang entfernen
    python3 verwaltung.py readme                Passwort-Übersicht und QR-Code neu schreiben

Nach jedem Befehl (außer liste/readme) läuft build.py; danach veröffentlichen:
    python3 veroeffentlichen.py --erzwingen
"""

import argparse
import json
import secrets
import subprocess
import sys
from datetime import date
from pathlib import Path

HIER = Path(__file__).resolve().parent
KONFIG = HIER / "zugangsdaten.json"

ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"   # ohne 0/O, 1/l/i — tippfreundlich


def neues_passwort(gruppen=4):
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(gruppen))


def lade():
    if not KONFIG.is_file():
        sys.exit("zugangsdaten.json fehlt — Vorlage: zugangsdaten.beispiel.json")
    return json.loads(KONFIG.read_text(encoding="utf-8"))


def speichere(cfg):
    KONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    schreibe_passwort_readme(cfg)


# ─────────────────────────── Passwort-Übersicht ─────────────────────────────

def qr_erzeugen(url: str, ziel: Path) -> bool:
    """QR-Code als PNG (Modul qrcode + pillow). Fehlt das Modul, gibt es keinen QR."""
    try:
        import qrcode
        img = qrcode.make(url, border=2, box_size=10)
        img.save(str(ziel))
        return True
    except Exception:
        return False


def werkzeugordner(cfg) -> Path:
    try:
        return Path(cfg["werkzeuge"]).expanduser()
    except Exception:
        return HIER


def schreibe_passwort_readme(cfg):
    """Lesbare Passwort-Übersicht in den OneDrive-Ordner „KI/Journal Mobil“ und
    nach „KI/Passwoerter“ schreiben — beides außerhalb des Repos, nie hochgeladen."""
    url = cfg.get("url") or "https://temmchen.github.io/journal-mobil/"
    ordner = werkzeugordner(cfg)
    if not ordner.is_dir():
        return
    qr = ordner / "QR-Journal-Mobil.png"
    hat_qr = qr_erzeugen(url, qr)
    stand = date.today().strftime("%d.%m.%Y")

    z = []
    z.append("# 🔐 Journal Mobil — Zugang und Passwort")
    z.append("")
    z.append("> ⚠️ **NUR für dich (OneDrive, privat).** Niemals ins Repo kopieren, niemals teilen.")
    z.append("> Diese Datei schreibt `verwaltung.py` **automatisch** — nicht von Hand pflegen.")
    z.append("> Quelle der Wahrheit: `_Portal-Setup/geheim/Mobil-zugangsdaten.json`.")
    z.append("")
    z.append(f"**Adresse:** {url}  ")
    z.append(f"**Schuljahr:** {cfg.get('schuljahr', '?')} · **Stand:** {stand}")
    z.append("")
    if hat_qr:
        z.append("**Am iPhone öffnen:** Kamera auf den Code halten, dann in Safari „Teilen → Zum Home-Bildschirm“.")
        z.append("")
        z.append("![QR-Code Journal Mobil](QR-Journal-Mobil.png)")
        z.append("")
    z.append("| Zugang | Passwort |")
    z.append("|---|---|")
    for zg in cfg.get("zugaenge", []):
        z.append(f"| **{zg.get('name', '?')}** | `{zg.get('passwort', '?')}` |")
    z.append("")
    z.append("Einloggen: Passwort exakt mit Bindestrichen, alles Kleinbuchstaben. Mit dem Häkchen")
    z.append("„Auf diesem iPhone angemeldet bleiben“ merkt sich das Handy den Tresor-Schlüssel —")
    z.append("„Abmelden“ löscht ihn wieder.")
    z.append("")
    z.append("## Gut zu wissen")
    z.append("")
    z.append("- Passwort ändern: `python3 ~/Documents/Journal-Mobil/verwaltung.py passwort \"<Name>\"`")
    z.append("  → der Tresor wird neu verschlüsselt, alte Anmeldungen auf dem Handy verfallen.")
    z.append("  Danach `Journal Mobil veröffentlichen.command` doppelklicken.")
    z.append("- Weiterer Zugang (z. B. iPad): `python3 ~/Documents/Journal-Mobil/verwaltung.py zugang \"iPad\"`")
    z.append("- Inhalte: Agenda (Stundenplan, Ferien, alle Einträge samt Dateien) und alle Skripte")
    z.append("  des aktuellen Schuljahres aus `KI/Journal de Classe/<Jahr>/`.")
    z.append("- Das Repo `temmchen/journal-mobil` ist öffentlich, enthält aber nur AES-256-Chiffrat.")
    text = "\n".join(z) + "\n"
    (ordner / "PASSWOERTER.md").write_text(text, encoding="utf-8")

    # Zweite Kopie neben den anderen Portal-Zugangsdaten (KI/Passwoerter/), ohne Bild-Link.
    passwoerter = ordner.parent / "Passwoerter"
    if passwoerter.is_dir():
        kopie = text.replace("![QR-Code Journal Mobil](QR-Journal-Mobil.png)",
                             "QR-Code: `KI/Journal Mobil/QR-Journal-Mobil.png`")
        (passwoerter / "Journal Mobil README.md").write_text(kopie, encoding="utf-8")


# ─────────────────────────── Befehle ────────────────────────────────────────

def baue(extra=()):
    print("\n— Tresor wird neu gebaut —", flush=True)
    r = subprocess.run([sys.executable, str(HIER / "build.py")] + list(extra))
    if r.returncode != 0:
        sys.exit("build.py ist fehlgeschlagen — Änderung ist gespeichert, aber noch nichts veröffentlicht.")


def abschluss(*zeilen):
    print()
    for z in zeilen:
        print(z)
    print("\nJetzt veröffentlichen:  python3 veroeffentlichen.py --erzwingen")
    print("(oder Doppelklick auf „Journal Mobil veröffentlichen.command“ — mit --erzwingen)")


def cmd_liste(cfg):
    print(f"Journal Mobil · {cfg.get('schuljahr', '?')} · {cfg.get('url', '')}")
    print(f"Inhalte aus: {cfg.get('inhalt', '?')}\n")
    for zg in cfg.get("zugaenge", []):
        print(f"  {zg.get('name', '?'):22s} Passwort: {zg.get('passwort', '?')}")


def finde(cfg, name):
    n = name.strip().lower()
    for zg in cfg.get("zugaenge", []):
        if str(zg.get("name", "")).strip().lower() == n:
            return zg
    return None


def cmd_passwort(cfg, wer):
    zg = finde(cfg, wer)
    if not zg:
        sys.exit(f"'{wer}' nicht gefunden — python3 verwaltung.py liste zeigt alle Zugänge.")
    zg["passwort"] = neues_passwort(4)
    speichere(cfg)
    baue(["--neu-verschluesseln"])          # alte Sitzungen auf dem Handy verfallen
    abschluss(f"✅ Neues Passwort für {zg['name']}: {zg['passwort']}",
              "   Der Tresor wurde neu verschlüsselt — auf dem Handy einmal neu anmelden.",
              "   Frühere Stände bleiben in der Git-Historie mit dem alten Passwort lesbar.")


def cmd_zugang(cfg, name):
    name = name.strip()
    if not name:
        sys.exit("Name fehlt.")
    if finde(cfg, name):
        sys.exit(f"Zugang '{name}' existiert schon.")
    pw = neues_passwort(4)
    cfg.setdefault("zugaenge", []).append({"name": name, "passwort": pw})
    speichere(cfg)
    baue()
    abschluss(f"✅ Zugang '{name}' angelegt — Passwort: {pw}")


def cmd_entfernen(cfg, name):
    zg = finde(cfg, name)
    if not zg:
        sys.exit(f"'{name}' nicht gefunden.")
    if len(cfg.get("zugaenge", [])) <= 1:
        sys.exit("Der letzte Zugang lässt sich nicht entfernen.")
    cfg["zugaenge"] = [z for z in cfg["zugaenge"] if z is not zg]
    speichere(cfg)
    baue(["--neu-verschluesseln"])
    abschluss(f"✅ Zugang '{zg['name']}' entfernt — Tresor neu verschlüsselt.")


def main():
    parser = argparse.ArgumentParser(description="Journal Mobil verwalten")
    sub = parser.add_subparsers(dest="befehl", required=True)
    sub.add_parser("liste", help="alle Zugänge anzeigen")
    sub.add_parser("readme", help="Passwort-Übersicht und QR-Code neu schreiben")
    p = sub.add_parser("passwort", help="Passwort neu würfeln")
    p.add_argument("wer", help="Name des Zugangs, z. B. \"Tom (iPhone)\"")
    p = sub.add_parser("zugang", help="weiteren Zugang anlegen")
    p.add_argument("name", help="Anzeigename, z. B. iPad")
    p = sub.add_parser("entfernen", help="Zugang entfernen")
    p.add_argument("name")
    args = parser.parse_args()

    cfg = lade()
    if args.befehl == "liste":
        cmd_liste(cfg)
    elif args.befehl == "readme":
        schreibe_passwort_readme(cfg)
        print("Passwort-Übersicht und QR-Code geschrieben.")
    elif args.befehl == "passwort":
        cmd_passwort(cfg, args.wer)
    elif args.befehl == "zugang":
        cmd_zugang(cfg, args.name)
    elif args.befehl == "entfernen":
        cmd_entfernen(cfg, args.name)


if __name__ == "__main__":
    main()
