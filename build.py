#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py — Journal Mobil · Verschlüsselungs-Build
==================================================

Liest aus dem Journal de Classe (OneDrive) genau das, was unterwegs auf dem
iPhone gebraucht wird — die **Agenda** (Stundenplan, Ausnahmen, Ferien und
alle Einträge des Schuljahres samt abgelegter Dateien) und die **Skripte**
(alle PDF je Klasse und Modul) — verschlüsselt alles mit AES-256-GCM und legt
nur Chiffrat unter docs/vaults/ ab. docs/ ist die GitHub-Pages-Wurzel: im
öffentlichen Repo liegt kein Klartext und kein Passwort.

Aufruf:
    python3 build.py                        normaler (inkrementeller) Build
    python3 build.py --jahr 2027-2028       ein anderes Schuljahr bauen
    python3 build.py --neu-verschluesseln   frischer Tresor-Schlüssel (Schlüsselrotation)
    python3 build.py --lokal                vollständige Fassung NUR für diesen Mac (alle Dateien,
                                            kein 6-Wochen-Fenster) nach
                                            ~/Library/Application Support/Journal Mobil/lokal/

6-Wochen-Fenster (seit 24.10.2026): Ins öffentliche Repo kommen die Dateien der
Einträge nur aus 6 Kalenderwochen (Vorgabe: 4 Wochen zurück, die laufende und die
nächste Woche). Die Einträge selbst (Text, Ampel, Tags) und alle Skripte bleiben
vollständig drin. Einstellbar in zugangsdaten.json → optionen:
dateifenster (true/false), dateien_wochen_zurueck (4), dateien_wochen_voraus (1).

Krypto-Design (muss zu docs/index.html passen — identisch mit dem
Schuljahr- und dem CdM-Portal):
  * Schlüsselableitung: PBKDF2-HMAC-SHA256, 600 000 Iterationen, Salt 16 B je Zugang
  * Umschlag-Verfahren: EIN zufälliger 256-Bit-Inhaltsschlüssel K für den Tresor;
    K wird für jeden Zugang einzeln "eingewickelt" (AES-GCM über JSON {k, rolle, label})
  * Manifest und Dateien: 12-B-Nonce || AES-256-GCM-Chiffrat (Tag enthalten)
  * Datei-Namen im Repo sind Zufalls-IDs; ändert sich eine Datei, bekommt sie
    eine NEUE ID — so darf das iPhone Dateien dauerhaft zwischenspeichern.

Der Journal-Ordner wird ausschließlich GELESEN.
"""

import argparse
import base64
import datetime
import json
import secrets
import shutil
import sys
import unicodedata
from pathlib import Path

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
except ImportError:
    sys.exit("Fehlendes Paket: bitte einmalig  pip3 install --user cryptography  ausführen.")

HIER = Path(__file__).resolve().parent
DOCS = HIER / "docs"
VAULTS = DOCS / "vaults"
KONFIG = HIER / "zugangsdaten.json"
BUILD_STATE = HIER / ".build-state.json"   # GEHEIM (gitignored): Tresor-Schlüssel + Datei-IDs
# Vollständige Fassung nur für den Mac (nie im Repo, nicht in iCloud/OneDrive)
LOKAL = Path.home() / "Library" / "Application Support" / "Journal Mobil" / "lokal"
HUELLE_DATEIEN = ("index.html", "sw.js", "manifest.webmanifest", ".nojekyll")
HUELLE_ORDNER = ("lib", "icons")

PBKDF2_ITER = 600_000
VAULT_NAME = "mobil"                        # es gibt genau einen Tresor

# Welche Teile der Journal-config.json das iPhone braucht (nichts Privates,
# aber auch keine Launcher-Pfade des Macs).
CONFIG_FELDER = ("zeitraster", "klassen", "klassen_alias", "cdm_kurse", "cdm_farbe",
                 "cdm_farbe_dunkel", "cdm_zeiten", "samstag_immer", "modul_zeitraum")

# Dateiendungen, die das iPhone anzeigen kann; alles andere wird trotzdem
# mitgenommen, aber nur zum Teilen/Sichern angeboten.
ANZEIGBAR = {"pdf", "png", "jpg", "jpeg", "gif", "webp", "txt", "md", "html", "htm"}


# ───────────────────────── Schuljahr ────────────────────────────────────────

def jahr_von(journal: Path) -> str:
    """EINE Quelle der Wahrheit: <Journal>/aktuelles-jahr.txt (z. B. 2026-2027)."""
    marke = journal / "aktuelles-jahr.txt"
    try:
        j = marke.read_text(encoding="utf-8").strip()
        if j:
            return j
    except Exception:
        pass
    jahre = sorted(p.name for p in journal.iterdir()
                   if p.is_dir() and len(p.name) == 9 and p.name[4] == "-" and p.name[:4].isdigit())
    return jahre[-1] if jahre else "2026-2027"


def jahr_anzeige(j: str) -> str:
    return j.replace("-", " – ")


# ─────────────────────────── Krypto-Bausteine ───────────────────────────────

def b64(daten: bytes) -> str:
    return base64.b64encode(daten).decode("ascii")


def leite_kek_ab(passwort: str, salt: bytes) -> bytes:
    """Key-Encryption-Key aus dem Passwort ableiten (NFC-normalisiert wie im Browser)."""
    pw = unicodedata.normalize("NFC", passwort).encode("utf-8")
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITER)
    return kdf.derive(pw)


def verschluessele(key: bytes, klartext: bytes) -> bytes:
    """12-B-Nonce || GCM-Chiffrat — Format für Manifest und Dateien."""
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key).encrypt(nonce, klartext, None)


def wickle_ein(kek: bytes, nutzlast: dict) -> dict:
    """Tresor-Schlüssel + Rolleninfo für einen Zugang einwickeln."""
    nonce = secrets.token_bytes(12)
    ct = AESGCM(kek).encrypt(nonce, json.dumps(nutzlast, ensure_ascii=False).encode("utf-8"), None)
    return {"iv": b64(nonce), "ct": b64(ct)}


# ─────────────────────────── 6-Wochen-Fenster ───────────────────────────────

def dateifenster(opt: dict, heute=None):
    """(von, bis) als ISO-Daten — die Kalenderwochen, deren Eintrags-Dateien ins Repo
    kommen; None = keine Grenze. Montag-genau, damit das Fenster nur montags weiterrückt
    (veroeffentlichen.py merkt das am Inventar und veröffentlicht dann von selbst)."""
    opt = opt or {}
    if not opt.get("dateifenster", True):
        return None
    zurueck = max(0, int(opt.get("dateien_wochen_zurueck", 4)))
    voraus = max(0, int(opt.get("dateien_wochen_voraus", 1)))
    h = heute or datetime.date.today()
    montag = h - datetime.timedelta(days=h.weekday())
    von = montag - datetime.timedelta(weeks=zurueck)
    bis = montag + datetime.timedelta(weeks=voraus + 1) - datetime.timedelta(days=1)
    return von.isoformat(), bis.isoformat()


def fenster_wochen(opt: dict) -> int:
    opt = opt or {}
    return int(opt.get("dateien_wochen_zurueck", 4)) + 1 + int(opt.get("dateien_wochen_voraus", 1))


# ─────────────────────────── Journal lesen ──────────────────────────────────

def json_lesen(pfad: Path, was: str):
    """JSON lesen; eine vorhandene, aber unlesbare Datei (OneDrive-Sync, Konfliktkopie)
    bricht den Build ab — es soll nie ein halber Stand aufs iPhone."""
    if not pfad.exists():
        return None
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except Exception as ex:
        sys.exit(f"{was} ist nicht lesbar ({pfad.name}): {ex}\n"
                 f"→ OneDrive fertig synchronisieren lassen, dann erneut veröffentlichen.")


def typ_von(name: str) -> str:
    return Path(name).suffix.lstrip(".").lower()


def sammle(cfg: dict, jahr: str, lokal: bool = False):
    """Alles einsammeln, was ins Manifest kommt. Dateien werden noch nicht gelesen —
    nur als (Schlüssel, Pfad) gemerkt; das Verschlüsseln übernimmt der Build."""
    journal = Path(cfg["inhalt"]).expanduser()
    jahresordner = journal / jahr
    if not jahresordner.is_dir():
        sys.exit(f"Jahresordner fehlt: {jahresordner}")
    opt = cfg.get("optionen") or {}
    nur_lehrer = bool(opt.get("nur_lehrer_einschliessen", True))
    mit_dateien = bool(opt.get("eintrags_dateien_einschliessen", True))
    max_bytes = int(float(opt.get("max_mb_je_datei", 40)) * 1024 * 1024)
    wochen = int(opt.get("wochen_rueckblick") or 0)
    fenster = None if lokal else dateifenster(opt)
    if lokal:
        max_bytes = 2 * 1024 ** 3          # am Mac: keine Größengrenze für Dateien
    ausserhalb = 0

    config_roh = json_lesen(journal / "config.json", "config.json") or {}
    config = {k: config_roh[k] for k in CONFIG_FELDER if k in config_roh}

    stundenplan = json_lesen(jahresordner / "stundenplan.json", "Stundenplan") or {}
    stundenplan = {"zeitraster": stundenplan.get("zeitraster") or config.get("zeitraster") or [],
                   "versionen": stundenplan.get("versionen") or [],
                   "ausnahmen": stundenplan.get("ausnahmen") or []}
    ferien = json_lesen(jahresordner / "ferien.json", "Ferien") or {}
    journal_json = json_lesen(jahresordner / "journal.json", "Journal") or {}
    skripte_json = json_lesen(jahresordner / "skripte.json", "Skripte") or {}

    dateien = []            # [(schluessel, Path, eintrag_dict)] — eintrag_dict bekommt fid
    uebersprungen = []      # zu groß / fehlt
    ab_datum = ""
    if wochen > 0:
        ab_datum = (datetime.date.today() - datetime.timedelta(weeks=wochen)).isoformat()

    # ── Einträge ──
    eintraege = []
    for e in journal_json.get("eintraege") or []:
        if not isinstance(e, dict) or not e.get("id"):
            continue
        if ab_datum and str(e.get("datum") or "") < ab_datum:
            continue
        kopie = {k: e.get(k) for k in ("id", "datum", "bereich", "klasse", "fach", "raum",
                                       "stunde_id", "von", "bis", "periode_von", "periode_bis",
                                       "typ", "titel", "text", "status", "tags",
                                       "erstellt", "geaendert")}
        kopie["dateien"] = []
        for d in e.get("dateien") or []:
            if not isinstance(d, dict) or not d.get("pfad"):
                continue
            eintrag = {"name": d.get("name") or Path(d["pfad"]).name,
                       "groesse": d.get("groesse") or 0,
                       "typ": typ_von(d.get("name") or d["pfad"]),
                       "fid": None}
            kopie["dateien"].append(eintrag)
            if not mit_dateien:
                eintrag["hinweis"] = "nicht übernommen"
                continue
            datum = str(e.get("datum") or "")
            if fenster and not (fenster[0] <= datum <= fenster[1]):
                eintrag["hinweis"] = "nur am Mac (außerhalb des 6-Wochen-Fensters)"
                ausserhalb += 1
                continue
            quelle = jahresordner / d["pfad"]
            if not quelle.is_file():
                eintrag["hinweis"] = "Datei fehlt"
                uebersprungen.append(f"{d['pfad']} (fehlt)")
                continue
            if quelle.stat().st_size > max_bytes:
                eintrag["hinweis"] = "zu groß fürs Handy"
                uebersprungen.append(f"{d['pfad']} (> {max_bytes // 1048576} MB)")
                continue
            dateien.append((f"{jahr}/{d['pfad']}", quelle, eintrag))
        eintraege.append(kopie)

    # ── Skripte ──
    skripte = []
    for s in skripte_json.get("skripte") or []:
        if not isinstance(s, dict) or not s.get("pfad"):
            continue
        if s.get("nur_lehrer") and not nur_lehrer:
            continue
        kopie = {k: s.get(k) for k in ("id", "klasse", "modul", "zeitraum", "art", "sprache",
                                       "titel", "name", "seiten", "groesse", "nur_lehrer",
                                       "aktualisiert")}
        kopie["typ"] = typ_von(s.get("name") or s["pfad"])
        kopie["fid"] = None
        quelle = jahresordner / s["pfad"]
        if not quelle.is_file():
            kopie["hinweis"] = "Datei fehlt"
            uebersprungen.append(f"{s['pfad']} (fehlt)")
        elif quelle.stat().st_size > max_bytes:
            kopie["hinweis"] = "zu groß fürs Handy"
            uebersprungen.append(f"{s['pfad']} (> {max_bytes // 1048576} MB)")
        else:
            dateien.append((f"{jahr}/{s['pfad']}", quelle, kopie))
        skripte.append(kopie)

    manifest = {
        "v": 1,
        "portal": "journal-mobil",
        "schuljahr": jahr,
        "schuljahr_text": jahr_anzeige(jahr),
        "config": config,
        "stundenplan": stundenplan,
        "ferien": ferien,
        "eintraege": eintraege,
        "skripte": skripte,
        "dateifenster": ({"von": fenster[0], "bis": fenster[1], "wochen": fenster_wochen(opt)}
                         if fenster else None),
        "ausserhalb_fenster": ausserhalb,
        "lokal": bool(lokal),
    }
    return manifest, dateien, uebersprungen


# ─────────────────────────── Haupt-Build ────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Journal Mobil verschlüsselt bauen")
    parser.add_argument("--jahr", help="Schuljahr, z. B. 2026-2027 (Vorgabe: aktuelles-jahr.txt)")
    parser.add_argument("--neu-verschluesseln", action="store_true",
                        help="Tresor mit frischem Schlüssel und frischen IDs neu aufbauen "
                             "(echte Schlüsselrotation; alte Sitzungen auf dem Handy verfallen)")
    parser.add_argument("--lokal", action="store_true",
                        help="vollständige Fassung nur für diesen Mac bauen (alle Dateien, kein "
                             "6-Wochen-Fenster) — Ziel: ~/Library/Application Support/Journal Mobil/lokal")
    args = parser.parse_args()

    global DOCS, VAULTS, BUILD_STATE
    if args.lokal:
        DOCS = LOKAL
        VAULTS = DOCS / "vaults"
        BUILD_STATE = DOCS / ".build-state.json"
        DOCS.mkdir(parents=True, exist_ok=True)
        # App-Hülle aus dem Repo übernehmen (immer frisch, damit die Vorschau den neuesten Code zeigt)
        quelle = HIER / "docs"
        for name in HUELLE_DATEIEN:
            if (quelle / name).is_file():
                shutil.copy2(quelle / name, DOCS / name)
        for name in HUELLE_ORDNER:
            if (quelle / name).is_dir():
                shutil.copytree(quelle / name, DOCS / name, dirs_exist_ok=True)
        print(f"🖥  Lokale Vollfassung für diesen Mac → {DOCS}")

    if not KONFIG.is_file():
        sys.exit("zugangsdaten.json fehlt — Vorlage: zugangsdaten.beispiel.json")
    cfg = json.loads(KONFIG.read_text(encoding="utf-8"))
    journal = Path(cfg["inhalt"]).expanduser()
    if not journal.is_dir():
        sys.exit(f"Journal-Ordner nicht gefunden: {journal}")
    jahr = args.jahr or jahr_von(journal)
    print(f"Schuljahr: {jahr_anzeige(jahr)}   (Journal: {journal})")

    # ── Zugänge (Principals) + Passwörter prüfen ──
    zugaenge = cfg.get("zugaenge") or []
    if not zugaenge:
        sys.exit("zugangsdaten.json braucht mindestens einen Zugang unter \"zugaenge\".")
    principals = []
    gesehen = []
    print("Zugänge:")
    for i, z in enumerate(zugaenge):
        passwort = unicodedata.normalize("NFC", str(z.get("passwort") or ""))
        label = z.get("name") or f"Zugang {i + 1}"
        if len(passwort) < 8:
            sys.exit(f"Passwort für '{label}' fehlt oder ist kürzer als 8 Zeichen.")
        if passwort in gesehen:
            sys.exit(f"Passwort für '{label}' ist doppelt vergeben.")
        gesehen.append(passwort)
        salt = secrets.token_bytes(16)
        pid = f"p{i}"
        print(f"  · {pid}: {label} — leite Schlüssel ab …")
        principals.append({"id": pid, "salt": salt, "kek": leite_kek_ab(passwort, salt),
                           "label": label, "rolle": "leser"})

    # ── Inhalte einsammeln ──
    manifest, dateien, uebersprungen = sammle(cfg, jahr, lokal=args.lokal)

    # ── Tresor (inkrementell) ──
    frisch = bool(args.neu_verschluesseln)
    if frisch and VAULTS.exists():
        shutil.rmtree(VAULTS)
    VAULTS.mkdir(parents=True, exist_ok=True)

    alt = {"vaults": {}, "dateien": {}}
    if not frisch:
        try:
            d = json.loads(BUILD_STATE.read_text(encoding="utf-8"))
            alt = {"vaults": d.get("vaults", {}), "dateien": d.get("dateien", {})}
        except Exception:
            pass
    if frisch:
        print("🔄 Neuverschlüsselung: der Tresor bekommt einen frischen Schlüssel.")

    vorher = alt["vaults"].get(VAULT_NAME)
    if vorher:
        vid = vorher["id"]
        k_vault = base64.b64decode(vorher["key"])
    else:
        vid = secrets.token_hex(8)
        k_vault = secrets.token_bytes(32)
    neu = {"vaults": {VAULT_NAME: {"id": vid, "key": b64(k_vault)}}, "dateien": {}}

    vdir = VAULTS / vid
    (vdir / "f").mkdir(parents=True, exist_ok=True)
    behalten = set()
    zaehler = {"neu": 0, "wiederverwendet": 0}
    gesamt = 0
    for schluessel, quelle, ziel in dateien:
        st = quelle.stat()
        vorher_d = alt["dateien"].get(schluessel)
        unveraendert = (vorher_d
                        and vorher_d.get("size") == st.st_size
                        and int(vorher_d.get("mtime", -1)) == int(st.st_mtime)
                        and (vdir / "f" / f"{vorher_d['fid']}.enc").exists())
        if unveraendert:
            fid = vorher_d["fid"]                       # Chiffrat bleibt Byte-gleich
            zaehler["wiederverwendet"] += 1
        else:
            # Geänderte Datei → NEUE Kennung, damit ein alter Cache auf dem Handy
            # nie ein veraltetes Chiffrat für die neue Fassung hält.
            fid = secrets.token_hex(12)
            (vdir / "f" / f"{fid}.enc").write_bytes(verschluessele(k_vault, quelle.read_bytes()))
            zaehler["neu"] += 1
        neu["dateien"][schluessel] = {"fid": fid, "size": st.st_size, "mtime": int(st.st_mtime)}
        behalten.add(f"{fid}.enc")
        ziel["fid"] = fid
        ziel["groesse"] = st.st_size
        gesamt += st.st_size
        if st.st_size > 95 * 1024 * 1024 and not args.lokal:
            print(f"  ⚠️  {quelle.name}: über 95 MB — GitHub-Limit ist 100 MB/Datei!")

    for veraltet in (vdir / "f").iterdir():             # gelöschte oder ersetzte Dateien aufräumen
        if veraltet.name not in behalten:
            veraltet.unlink()
    for anderer in VAULTS.iterdir():                     # fremde Tresore (alte IDs) entfernen
        if anderer.is_dir() and anderer.name != vid:
            shutil.rmtree(anderer)

    build_id = secrets.token_hex(6)
    jetzt = datetime.datetime.now().replace(microsecond=0).isoformat()
    manifest["erstellt"] = jetzt
    manifest["build"] = build_id
    manifest["statistik"] = {
        "eintraege": len(manifest["eintraege"]),
        "skripte": len(manifest["skripte"]),
        "dateien": len(dateien),
        "bytes": gesamt,
        "uebersprungen": uebersprungen,
        "ausserhalb_fenster": manifest.pop("ausserhalb_fenster", 0),
    }
    (vdir / "m.enc").write_bytes(
        verschluessele(k_vault, json.dumps(manifest, ensure_ascii=False).encode("utf-8")))

    wraps = []
    for pr in principals:
        w = wickle_ein(pr["kek"], {"k": b64(k_vault), "rolle": pr["rolle"], "label": pr["label"]})
        w["p"] = pr["id"]
        wraps.append(w)

    index = {
        "v": 1,
        "portal": "journal-mobil",
        "schuljahr": jahr_anzeige(jahr),
        "erstellt": jetzt,
        "build": build_id,
        "kdf": {"typ": "PBKDF2-SHA256", "iter": PBKDF2_ITER},
        "principals": [{"id": p["id"], "salt": b64(p["salt"])} for p in principals],
        "vaults": [{"id": vid, "wraps": wraps, "manifest": f"vaults/{vid}/m.enc"}],
    }
    (VAULTS / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    (DOCS / ".nojekyll").write_text("")
    BUILD_STATE.write_text(json.dumps(neu, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── Zusammenfassung ──
    st = manifest["statistik"]
    print(f"\nVerschlüsselt: {zaehler['neu']} Datei(en) neu, "
          f"{zaehler['wiederverwendet']} unverändert übernommen.")
    print(f"Inhalt: {st['eintraege']} Einträge · {st['skripte']} Skripte · "
          f"{st['dateien']} Dateien · {gesamt / 1024 / 1024:.1f} MiB")
    if manifest.get("dateifenster"):
        f = manifest["dateifenster"]
        print(f"6-Wochen-Fenster: Eintrags-Dateien vom {f['von']} bis {f['bis']} — "
              f"{st['ausserhalb_fenster']} ältere/spätere Datei(en) bleiben nur am Mac.")
    if uebersprungen:
        print(f"Übersprungen ({len(uebersprungen)}):")
        for u in uebersprungen:
            print(f"  – {u}")
    print("Fertig. Lokale Vollfassung — Vorschau: „Journal Mobil Vorschau.command“." if args.lokal
          else "Fertig. → docs/ committen und pushen, Passwörter bleiben lokal.")


if __name__ == "__main__":
    main()
