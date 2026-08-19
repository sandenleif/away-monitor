# away-monitor

Sperrt Windows, wenn die Kamera niemanden mehr vor dem Rechner sieht.

Läuft als Tray-Icon, braucht keine Adminrechte, kein Cloud-Dienst. Bilder
verlassen den Rechner nicht und werden auch nicht gespeichert.

## Wie entschieden wird

Der Zustandsautomat kennt zwei Anwesenheitssignale — die Kamera und die
Tastatur/Maus — und in der ausgelieferten Einstellung ist **nur die Kamera
aktiv**:

```
idle_before_camera = 0      # Kamera läuft dauerhaft, Eingabe zählt nicht
absence_grace      = 20     # 20 s ohne Gesicht → Warnung
warning_seconds    = 5      # 5 s Countdown → gesperrt
```

Ab dem Moment, in dem dein Gesicht aus dem Bild verschwindet, vergehen also
20 Sekunden bis zur Warnung und 25 bis zur Sperre.

**Das ist die scharfe Einstellung, und sie hat einen Preis:** Tippen schützt
dich nicht. Wer sich zur Seite dreht, ins Gegenlicht gerät oder aus dem
Bildausschnitt rutscht, wird gesperrt — auch mitten im Schreiben. Die Kamera
läuft außerdem durchgehend, die LED ist also immer an.

Wer das entschärfen will, setzt `idle_before_camera` auf z. B. 45. Dann gilt:
solange du tippst, bleibt die Kamera aus und die Uhr steht. Erst nach 45 s ohne
Eingabe schaut die Kamera überhaupt nach. Das kostet Reaktionszeit, killt aber
die allermeisten Fehlalarme.

Drei Sicherungen greifen unabhängig davon:

- **Aufwärmphase** — die ersten Bilder nach dem Kameraöffnen sind oft schwarz
  und zählen nie als Abwesenheit.
- **Kamera nicht verfügbar** (z. B. weil Teams sie belegt) heißt standardmäßig
  *anwesend*. Eine belegte Kamera bedeutet meist Videocall.
- **Countdown mit Abbruch** — vor dem Sperren erscheint ein Overlay. Maus
  bewegen, Esc drücken oder „Ich bin da" klicken bricht ab.

Zustände: `aktiv` (du tippst, nur bei `idle_before_camera > 0`) →
`beobachte` → `Warnung` → `gesperrt`.

## Loslegen

Fertige Exe aus dem Release herunterladen, in einen eigenen Ordner legen,
doppelklicken. Sie braucht keine Installation und legt `config.toml` und
`away-monitor.log` neben sich an.

Vorher prüfen, ob deine Kamera mitspielt:

```
away-monitor.exe --check
```

Das Ergebnis steht in `away-monitor.log` — die Exe hat kein Konsolenfenster.

Automatisch beim Anmelden starten: eine Verknüpfung zur Exe in den
Autostart-Ordner legen (`Win+R`, `shell:startup`).

## Aus dem Quellcode

```
uv venv --python 3.14
uv pip install -r requirements.txt
.venv\Scripts\python.exe scripts\fetch_model.py
.venv\Scripts\python.exe -m away_monitor --check
run.cmd
```

Ohne `uv` geht auch `python -m venv .venv` und
`.venv\Scripts\pip install -r requirements.txt`.

`run.cmd` wechselt selbst ins Projektverzeichnis und reicht Argumente durch, du
kannst es also von überall mit vollem Pfad aufrufen — auch `run.cmd --live`.
Direkte Aufrufe sind dagegen relativ; von einem anderen Laufwerk aus braucht
`cd` deshalb ein `/d`:

```
cd /d "C:\Users\...\away-monitor"
.venv\Scripts\python.exe -m away_monitor --live
```

Für `--check` und `-v` nimm `python.exe` statt `run.cmd`: letzteres startet mit
`pythonw.exe`, das keine Konsole hat und die Ausgabe verschluckt.

## Live-Ansicht

Rechtsklick aufs Tray-Icon → **Live-Ansicht**, oder direkt mit `--live` starten.
Sie zeigt das Kamerabild mit den erkannten Boxen samt Score und daneben, was der
Automat gerade denkt: Leerlauf, Sekunden seit dem letzten Gesicht, laufender
Countdown, Rechenzeit pro Bild.

Dafür ist sie da: **Schwelle einstellen, ohne zu raten.** Der Regler wirkt
sofort — YuNet nimmt die neue Schwelle im laufenden Betrieb an. Passt der Wert,
schreibt „Speichern" ihn in die `config.toml`, Kommentare bleiben erhalten.

Der sichere Einstellmodus ist **Live-Ansicht + „Überwachung pausiert"**: Bild
und Zahlen laufen weiter, gesperrt wird nichts. So findest du in Ruhe heraus, ab
wann dein Gegenlicht die Erkennung kippen lässt.

Solange das Fenster offen ist, tastet der Automat 10×/s ab statt 2×/s, damit das
Bild flüssig läuft. Das verschiebt keine Schwellwerte — gerechnet wird mit der
Wanduhr, nicht mit Takten. Kostet ~15 ms CPU pro Bild.

Mit „Kamerabild anzeigen" lässt sich das Video ausblenden — dann siehst du nur
die Boxen auf schwarzem Grund.

## Notizzettel

Tray → **Notizzettel** blendet ein kleines Fenster ein, das immer im Vordergrund
bleibt: farbiger Punkt für den Zustand, die Kurzbegründung darunter, und sobald
der Countdown läuft, die verbleibenden Sekunden groß daneben.

Gedacht für den Fall, dass man wissen will, was die App gerade denkt, ohne die
Live-Ansicht offen zu lassen — die hält die Kamera an und kostet CPU, der Zettel
nicht. Er zeigt nur Text und braucht kein Kamerabild.

Verschieben durch Ziehen; die Position wird gemerkt und beim nächsten Start
wiederhergestellt. Ein- und ausschalten über das Tray-Menü oder `--sticky`,
Deckkraft über `opacity` in der `config.toml`.

## Updates

Die App aktualisiert sich selbst aus GitHub-Releases. Ihre Herkunft ist fest
voreingestellt — eine frisch heruntergeladene Exe findet ihre Updates ohne
Zutun:

```toml
[update]
repository = "sandenleif/away-monitor"
check_on_start = true
require_checksum = true
```

Die Zeile zu leeren oder zu löschen schaltet **nichts** ab: die App trägt ihre
Herkunft beim nächsten Start wieder ein. Das ist Absicht — eine über Versionen
mitgeschleppte `config.toml` soll nicht dazu führen, dass stillschweigend nie
wieder nach Updates gesehen wird. Zum Abschalten gibt es `check_on_start =
false`. Wer einen Fork pflegt, trägt ihn ein und bekommt die Updates von dort;
ein gesetzter Wert wird nie überschrieben.

Die App sieht acht Sekunden nach dem Start einmal nach und
meldet sich nur, wenn es wirklich etwas Neueres gibt. Manuell geht es über
Tray → **Nach Updates suchen** oder `away-monitor.exe --check-update`.

Der Ablauf ist bewusst in Schritte zerlegt, damit nichts hinter deinem Rücken
passiert:

1. Nur die API wird gefragt — es wird nichts geladen.
2. Ein Dialog zeigt Version und Release-Notizen und fragt nach.
3. Erst dann wird geladen, die veröffentlichte SHA256 geprüft und verglichen.
4. Stimmt die Prüfsumme nicht — oder fehlt sie ganz — wird **nichts**
   installiert. `require_checksum = false` hebt das auf; lass es besser an.
5. Die laufende Exe wird zur Seite geschoben (`away-monitor.old.exe`), die neue
   nimmt ihren Platz ein, die neue Version startet, die alte beendet sich.
   Beim nächsten Start wird die Sicherung entfernt.

Schlägt Schritt 5 fehl, wird die alte Version zurückgerollt.

Abgesichert ist der Weg über eine Host-Positivliste (nur `github.com` und
`api.github.com`, nur HTTPS), ein Größenlimit für den Download und die
Pflicht-Prüfsumme. Ein Netzfehler bleibt folgenlos: die Prüfung gibt auf und die
App läuft weiter.

## Release bauen

```
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

Läuft erst die Tests, baut dann `dist\away-monitor.exe` (~72 MB, alles
eingebettet — Python, OpenCV, das Modell) und schreibt die passende
`away-monitor.exe.sha256`.

Veröffentlichen macht ein Befehl — Tests, Build, Tag, Upload:

```
# away_monitor/__init__.py: __version__ hochsetzen, dann
powershell -ExecutionPolicy Bypass -File scripts\release.ps1
```

Mit `-DryRun` läuft alles bis zum Veröffentlichen und hält davor an. Das Skript
weigert sich bei uncommitteten Änderungen und bei einem Tag, den es schon gibt —
sonst passt das Release nicht zum Stand im Repo. Es braucht nur den
`repo`-Scope, keinen `workflow`-Scope.

Wer es lieber in der CI hätte: `.github/workflows/release.yml` im Projekt tut
dasselbe bei einem Tag `v*`. Das Anlegen dieser Datei verlangt allerdings ein
Token mit `workflow`-Scope — über die GitHub-Weboberfläche geht es ohne.

Hinweis: PyInstaller-Builds sind nicht bitgenau reproduzierbar (eingebettete
Zeitstempel). Ein Neubau derselben Quellen ergibt eine andere Prüfsumme. Die
maßgebliche steht deshalb immer neben der veröffentlichten Exe im Release.

## Kommandozeile

| Flag | Wirkung |
|---|---|
| `--live` | Live-Ansicht direkt beim Start öffnen |
| `--sticky` | Notizzettel direkt beim Start einblenden |
| `--check` | Modell, Kamera und Erkennung einmal prüfen, dann beenden |
| `--check-update` | einmal nach einem Update sehen, dann beenden |
| `--dry-run` | protokolliert „würde jetzt sperren", statt zu sperren |
| `--config PFAD` | andere `config.toml` verwenden |
| `--version` | Versionsnummer ausgeben |
| `-v` | Debug-Logging |

Zum Einstellen der Zeiten: `--dry-run` zusammen mit `-v` laufen lassen und ins
Log schauen, statt sich versehentlich auszusperren.

## Konfiguration

`config.toml` wird beim ersten Start neben der Exe angelegt, mit Kommentaren zu
jedem Wert. Die drei Stellschrauben, die man wirklich anfasst:

| Wert | Default | Bedeutung |
|---|---|---|
| `idle_before_camera` | 0 | Leerlauf, bevor die Kamera angeht. 0 = immer an |
| `absence_grace` | 20 s | ohne erkanntes Gesicht bis zur Warnung |
| `warning_seconds` | 5 s | Countdown zum Abbrechen |

Weitere Werte: `score_threshold` (0.6; niedriger = empfindlicher bei schlechtem
Licht, aber anfälliger für Poster und Fotos), `on_camera_error`
(`never_lock` / `lock`), `camera.index`, `open_retry_seconds`,
`release_when_active`, `[preview]` für die Live-Ansicht, `[sticky]` für den
Notizzettel (Sichtbarkeit, gemerkte Position, Deckkraft) und `[update]` für die
Selbstaktualisierung.

Änderungen wirken nach einem Neustart der App — außer `score_threshold`, wenn du
ihn über die Live-Ansicht setzt.

## Wenn es nicht tut

**Sperrt, obwohl ich da bin.** Meist Gegenlicht: ein Fenster hinter dir macht
das Gesicht zur Silhouette. Mehr Licht von vorn, oder `score_threshold` auf 0.5.
Mit `--check` siehst du sofort, wie viele Bilder erkannt werden; mit `--live`
siehst du *warum* — und kannst die Schwelle direkt am Regler nachziehen. Wenn es
oft passiert, ist `idle_before_camera = 45` das wirksamste Gegenmittel.

**Sperrt nie.** `--check` zeigt, ob die Kamera überhaupt aufgeht. Häufig
verboten unter *Einstellungen → Datenschutz → Kamera → Desktop-Apps*. Steht im
Log dauernd „Kamera mit keinem Backend zu öffnen", greift bei `never_lock`
absichtlich nie die Sperre — dann `on_camera_error = "lock"` setzen oder die
belegende App schließen.

**„away-monitor läuft bereits".** Ein benannter Mutex verhindert zwei
Instanzen — die zweite bekäme nie ein Bild, weil DirectShow die Kamera exklusiv
vergibt. Die laufende Instanz sitzt im Infobereich der Taskleiste.

**Die Exe startet langsam.** Rund 6 Sekunden. Onefile packt bei jedem Start
71 MB in ein Temp-Verzeichnis aus. Für eine Autostart-App vertretbar; der
Updater muss dafür nur eine einzige Datei tauschen.

## Grenzen

Ehrlich gesagt, bevor du dich drauf verlässt:

- **Kein Sicherheitsprodukt.** Das Tool ist eine Bequemlichkeit gegen
  offenstehende Sitzungen, keine Zugangskontrolle. Wer an der Tastatur sitzt,
  kann es über das Tray beenden.
- **Es erkennt Gesichter, nicht *dich*.** Wer sich vor die Kamera setzt, hält
  den Rechner offen. Ein gerahmtes Foto im Bildausschnitt übrigens auch.
- **Vollbild-Apps** (Spiele, manche Player) können das Warn-Overlay verdecken.
  Das Sperren funktioniert trotzdem, nur der Countdown ist dann unsichtbar.
- **Nur die eigene Sitzung.** Auf dem Sperrbildschirm läuft nichts, und über
  Remotedesktop ist der Kamerazugriff meist nicht verfügbar.
- **Die Exe ist nicht signiert.** SmartScreen wird beim ersten Start warnen.

Wer *„nur ich halte den Rechner offen"* braucht, kommt um Gesichts-*erkennung*
statt -*detektion* nicht herum (Embeddings via InsightFace o. ä.) — das ist
deutlich mehr Aufwand und will sauber getunt werden.

## Tests

```
.venv\Scripts\python.exe -m unittest discover -s tests
```

77 Tests, fast alle ohne Hardware. Der Zustandsautomat läuft gegen Fakes an
einer Fake-Uhr, die Kamera gegen ein Fake-cv2, der Updater gegen einen lokalen
HTTP-Server. Abgedeckt sind unter anderem:

- Aufwärmphase, Abbruch während des Countdowns, belegte Kamera in beiden Modi
- der 32-Bit-Überlauf der Windows-Idle-Zeit nach 49,7 Tagen Uptime
- die Live-Ansicht (Kamera bleibt trotz Eingabe offen, Schnappschüsse tragen
  Boxen und Countdown, im Einstellmodus wird nie gesperrt)
- Versionsvergleich, abgelehnte URLs (fremder Host, HTTP, `file://`),
  Prüfsummenkontrolle, Dateitausch samt Rollback, Größenlimit
- die Instanzsperre

Die Tests zum echten Detektor überspringen sich selbst, wenn das ONNX-Modell
fehlt.

## Wie es gebaut ist

| Datei | Zweck |
|---|---|
| `away_monitor/monitor.py` | Zustandsautomat — hier steckt die eigentliche Logik |
| `away_monitor/winapi.py` | Idle-Zeit, Sperren, Sperr-Erkennung, Instanzsperre |
| `away_monitor/camera.py` | Kamera öffnen/freigeben, Backend-Fallback, Aufwärmphase |
| `away_monitor/detector.py` | YuNet-Gesichtserkennung (~15 ms/Bild) |
| `away_monitor/ui.py` | Overlay, Live-Ansicht und Notizzettel (Tk im Hauptthread) |
| `away_monitor/theme.py` | Farben, Abstände, Schriften, Windows-Fensterrahmen |
| `away_monitor/widgets.py` | Schalter, Regler, Ring — als PIL-Bilder gezeichnet |
| `away_monitor/tray.py` | Tray-Icon und Menü |
| `away_monitor/updater.py` | Releases prüfen, laden, verifizieren, tauschen |
| `entry.py` | Startpunkt für PyInstaller (relative Importe brauchen ein Paket) |

Drei Threads: Tk im Hauptthread, der Monitor als Worker, pystray daneben.
Tk-Aufrufe gehen ausschließlich über eine Queue in den Hauptthread.

Tkinter bringt weder Schalter noch Regler mit, die nach 2020 aussehen, und
zeichnet Rundungen ohne Kantenglättung. Sie entstehen deshalb als PIL-Bilder:
vierfach überabgetastet gerendert, heruntergerechnet und als Bild in ein Label
gelegt. Titelleiste und Fensterecken kommen über `dwmapi` vom System — auf
älteren Windows-Versionen passiert dabei schlicht nichts.

Die Live-Ansicht greift **nicht** selbst auf die Kamera zu — DirectShow gibt sie
exklusiv heraus, ein zweiter Zugriff würde scheitern. Stattdessen legt der
Monitor je Takt einen `Snapshot` (Bild, Boxen, Zustand, Zeiten) in ein Fach, das
die Anzeige ausliest. Ist sie zu langsam, wird überschrieben statt gepuffert:
bei einem Livebild ist das jüngste das einzig interessante.

Die Kamera wird mit DirectShow geöffnet (~0,5 s), MSMF nur als Fallback — MSMF
braucht auf typischer Hardware über 10 s zum Öffnen.

Im gepackten Zustand liegen das Modell im Auspackverzeichnis von PyInstaller,
`config.toml` und Log dagegen neben der Exe. Das Auspackverzeichnis wird bei
jedem Start neu angelegt; Einstellungen wären dort sofort wieder weg.
