#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
veroeffentlichen.py — Ein-Klick-Veröffentlichung für Journal Mobil
===================================================================

Gedacht für den Doppelklick auf „Journal Mobil veröffentlichen.command" im
OneDrive-Ordner KI/Journal Mobil — und für den Portal-Wächter, der alle
20 Minuten `--pruefen` aufruft und bei „OFFEN" selbst veröffentlicht.

  1. holt den GitHub-Stand ab (git pull)
  2. vergleicht Journal-Daten (journal.json, stundenplan.json, ferien.json,
     skripte.json, config.json) und alle Skript- und Eintrags-Dateien mit dem
     Stand der letzten Veröffentlichung
  3. baut verschlüsselt neu, committet, pusht — nur wenn sich etwas geändert hat

    python3 veroeffentlichen.py              prüfen und bei Bedarf veröffentlichen
    python3 veroeffentlichen.py --pruefen    nur nachsehen: NICHTS-ZU-TUN / OFFEN
    python3 veroeffentlichen.py --erzwingen  auch ohne Datei-Änderung bauen und pushen
                                             (nach Code- oder Passwort-Änderungen)
"""

import json
import subprocess
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
KONFIG = HIER / "zugangsdaten.json"
STAND = HIER / ".letzter-stand.json"          # lokales Gedächtnis (gitignored)
DATEN = ("journal.json", "stundenplan.json", "ferien.json", "skripte.json")


def jahr_von(journal: Path) -> str:
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


def sag(text=""):
    print(text, flush=True)


def git(*args, fehler_ok=False):
    r = subprocess.run(["git", "-C", str(HIER)] + list(args), capture_output=True, text=True)
    if r.returncode != 0 and not fehler_ok:
        sag(f"❌ git {' '.join(args)} fehlgeschlagen:\n{r.stderr.strip()}")
        sys.exit(1)
    return r


def stat_von(p: Path):
    st = p.stat()
    return [st.st_size, int(st.st_mtime)]


def inventar(cfg):
    """Alles, was in den Build eingeht: {relativer Pfad: [Größe, mtime]}."""
    journal = Path(cfg["inhalt"]).expanduser()
    jahr = jahr_von(journal)
    jo = journal / jahr
    inv = {}
    if (journal / "config.json").is_file():
        inv["config.json"] = stat_von(journal / "config.json")
    for name in DATEN:
        p = jo / name
        if p.is_file():
            inv[f"{jahr}/{name}"] = stat_von(p)
    skripte = jo / "Skripte"
    if skripte.is_dir():
        for p in sorted(skripte.rglob("*")):
            if p.is_file() and not p.name.startswith("."):
                inv[f"{jahr}/{p.relative_to(jo).as_posix()}"] = stat_von(p)
    # Eintrags-Dateien: nur die, auf die ein Eintrag verweist (Papierkorb zählt nicht)
    try:
        eintraege = json.loads((jo / "journal.json").read_text(encoding="utf-8")).get("eintraege") or []
    except Exception:
        eintraege = []
    for e in eintraege:
        for d in (e.get("dateien") or []) if isinstance(e, dict) else []:
            pf = d.get("pfad") if isinstance(d, dict) else None
            if pf and (jo / pf).is_file():
                inv[f"{jahr}/{pf}"] = stat_von(jo / pf)
    return inv, jahr


def main():
    if not KONFIG.is_file():
        sys.exit("zugangsdaten.json fehlt im Repo-Ordner (Verknüpfung nach _Portal-Setup/geheim).")
    cfg = json.loads(KONFIG.read_text(encoding="utf-8"))
    url = cfg.get("url") or "https://temmchen.github.io/journal-mobil/"
    journal = Path(cfg["inhalt"]).expanduser()
    if not journal.is_dir():
        sys.exit(f"Journal-Ordner nicht gefunden: {journal}")

    stand_alt = {}
    if STAND.is_file():
        try:
            stand_alt = json.loads(STAND.read_text(encoding="utf-8"))
        except Exception:
            stand_alt = {}

    # --pruefen: nur nachsehen, nichts anfassen (Portal-Wächter)
    if "--pruefen" in sys.argv:
        jetzt, _jahr = inventar(cfg)
        git("fetch", "--quiet", "origin", "main", fehler_ok=True)
        voraus = git("rev-list", "--count", "HEAD..origin/main", fehler_ok=True).stdout.strip() or "0"
        if jetzt == stand_alt.get("inventar", {}) and voraus == "0":
            print("NICHTS-ZU-TUN")
        else:
            print("OFFEN")
        return

    sag("📱 Journal Mobil — Prüfen & Veröffentlichen")
    sag("=" * 44)

    # 1) GitHub-Stand holen
    hat_remote = bool(git("remote", fehler_ok=True).stdout.strip())
    if not hat_remote:
        sys.exit("❌ Kein GitHub-Remote eingerichtet — bitte „Journal Mobil einrichten.command“ ausführen.")
    sag("\n① Hole aktuellen Stand von GitHub …")
    pull = git("pull", "--no-rebase", "--quiet", "origin", "main", fehler_ok=True)
    if pull.returncode != 0:
        sag(f"❌ git pull fehlgeschlagen — bitte zuerst am Mac aufräumen:\n{pull.stderr.strip()}")
        sys.exit(1)

    # 2) Änderungen seit der letzten Veröffentlichung
    jetzt, jahr = inventar(cfg)
    alt = stand_alt.get("inventar", {})
    neu = sorted(set(jetzt) - set(alt))
    weg = sorted(set(alt) - set(jetzt))
    geaendert = sorted(k for k in set(jetzt) & set(alt) if jetzt[k] != alt[k])
    sag(f"\n② Schuljahr {jahr.replace('-', ' – ')} — Änderungen seit der letzten Veröffentlichung:"
        if stand_alt else "\n② Erste Veröffentlichung mit diesem Werkzeug — nehme alles auf:")
    for k in neu[:15]:
        sag(f"   + {k}")
    if len(neu) > 15:
        sag(f"   + … und {len(neu) - 15} weitere")
    for k in geaendert[:10]:
        sag(f"   ~ {k}")
    if len(geaendert) > 10:
        sag(f"   ~ … und {len(geaendert) - 10} weitere")
    for k in weg[:10]:
        sag(f"   − {k}")
    if not (neu or geaendert or weg):
        sag("   (keine Änderungen)")

    erzwingen = "--erzwingen" in sys.argv
    if erzwingen:
        sag("   (--erzwingen: baue und veröffentliche auch ohne Änderung)")
    if not (neu or geaendert or weg or erzwingen):
        sag("\n✅ Alles aktuell — das iPhone hat schon den neuesten Stand.")
        STAND.write_text(json.dumps({"inventar": jetzt}), encoding="utf-8")
        return

    # 3) Bauen
    sag("\n③ Baue verschlüsselt neu …")
    r = subprocess.run([sys.executable, str(HIER / "build.py")])
    if r.returncode != 0:
        sys.exit("❌ build.py fehlgeschlagen — es wurde nichts veröffentlicht.")

    # 4) Veröffentlichen — bewusst NUR die Tresor-Daten; Änderungen an index.html o. Ä.
    #    werden getrennt committet (sonst ginge Halbfertiges ungeprüft online).
    teile = []
    if neu:
        teile.append(f"{len(neu)} neu")
    if geaendert:
        teile.append(f"{len(geaendert)} geändert")
    if weg:
        teile.append(f"{len(weg)} entfernt")
    nachricht = "Inhalte aktualisiert: " + (", ".join(teile) if teile else "neu gebaut")

    sag("④ Veröffentliche …")
    git("add", "docs/vaults", "docs/.nojekyll")
    andere = [z for z in git("status", "--porcelain", "--", "docs", fehler_ok=True).stdout.splitlines()
              if z and not z[3:].startswith("docs/vaults") and not z[3:].endswith(".nojekyll")]
    if andere:
        sag("   ℹ️  Lokal geändert, wird NICHT mitveröffentlicht (bei Bedarf manuell committen):")
        for z in andere[:5]:
            sag(f"      {z[3:]}")
    commit = git("commit", "-q", "-m", nachricht, fehler_ok=True)
    if commit.returncode != 0 and "nothing to commit" not in (commit.stdout + commit.stderr):
        sag(f"❌ git commit: {commit.stderr.strip()}")
        sys.exit(1)
    git("push", "-q", "origin", "main")

    STAND.write_text(json.dumps({"inventar": jetzt}), encoding="utf-8")
    sag(f"\n✅ Fertig! In 1–2 Minuten online: {url}")
    sag("   Auf dem iPhone: Journal Mobil öffnen — es lädt den neuen Stand von selbst.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sag("\nAbgebrochen — es wurde nichts veröffentlicht.")
