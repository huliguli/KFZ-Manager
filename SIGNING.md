# Code-Signierung

Sowohl das innere Programm (`KFZManager.exe` im onedir-Build) als auch der
ausgelieferte **Installer** (`KFZManager-Setup.exe`) werden mit
**Authenticode** (SHA-256) und einem **RFC3161-Zeitstempel** signiert. Die
Signier-Pipeline ist **zertifikat-agnostisch**: ein Wechsel von einem
self-signed auf ein echtes OV/EV-Zertifikat ist nur ein Austausch der beiden
Secrets – kein Code muss geändert werden.

## Ehrliche Einordnung (self-signed)

Aktuell wird ein **selbst-signiertes** Zertifikat verwendet. Das entfernt die
Meldung „Unbekannter Herausgeber" **nur auf Rechnern, die dem Zertifikat
vertrauen**. **Fremde Rechner sehen weiterhin eine Windows-SmartScreen-Warnung** –
self-signed schafft kein öffentliches Vertrauen. Für echtes, geräteübergreifendes
Vertrauen ist ein **OV- oder EV-Code-Signing-Zertifikat** einer anerkannten CA nötig.

Der In-App-Updater verlässt sich deshalb nicht auf den Vertrauensstatus,
sondern **pinnt den Zertifikats-Thumbprint** (`_TRUSTED_CERT_THUMBPRINTS` in
`src/modules/updater/updater.py`): nur ein Installer, der mit exakt unserem
Schlüssel signiert wurde, wird ausgeführt (fail closed).

## Lokal: Zertifikat erstellen & signieren

```powershell
# 1) Self-signed Zertifikat + starkes Zufallspasswort erzeugen (Ausgabe einmalig sichern!)
#    -Trust hinterlegt es zusätzlich lokal (der Root-Import fragt einmal interaktiv nach).
.\tools\make-cert.ps1 -Trust

# 2) Bauen + Installer signieren in einem Schritt
.\build.ps1 -Sign

# 3) Signatur prüfen (zeigt Status + Zeitstempel)
& "C:\Program Files (x86)\Windows Kits\10\bin\<sdk>\x64\signtool.exe" verify /pa /v dist\KFZManager-Setup.exe
```

`cert\` (PFX/CER) ist **git-ignoriert** und darf **niemals** committet werden.

Nach einem Zertifikatswechsel den neuen Thumbprint in
`src/modules/updater/updater.py` pinnen — im **selben** Release, das erstmals
damit signiert (Alt-Clients pinnen den alten Wert; diese eine Umstellung
braucht einen manuellen Download).

## CI: automatisches Signieren im Release

Der Workflow [`.github/workflows/release.yml`](.github/workflows/release.yml)
baut den onedir-Build, signiert das innere Programm, schnürt den Installer,
signiert diesen, verifiziert die Signatur **gegen den Client-Pin** und
berechnet **danach** die Prüfsumme:

```
onedir-Build → inneres exe signieren → Installer (Inno Setup) → Installer signieren
            → Pin-Verifikation → SHA-256 (über die signierte Setup.exe) → Artefakt
```

Ausgelöst wird der Workflow durch das Pushen eines **annotierten Tags**
`vX.Y.Z` (erste Zeile der Tag-Nachricht = Release-Titel, Rest = Notes). Ein
eigener `publish`-Job legt das Release als **Entwurf** an, hängt alle vier
Dateien an und **veröffentlicht erst danach** — so existiert nie ein
sichtbares Release ohne Programmdateien.

Benötigte **GitHub-Actions-Secrets**:

| Secret | Inhalt |
| --- | --- |
| `CODESIGN_PFX_BASE64` | Die `.pfx` als Base64 (`[Convert]::ToBase64String([IO.File]::ReadAllBytes("cert\KFZManager.pfx"))`) |
| `CODESIGN_PFX_PASSWORD` | Das PFX-Passwort |

Bei einem **Tag-Build** ist das Zertifikat Pflicht (der Workflow bricht sonst
ab — ein unsigniertes Release würde jedes Auto-Update dauerhaft stoppen).

## Prüfsummen-Verifikation im Updater

Der In-App-Updater lädt den **Installer** über HTTPS (nur GitHub-Hosts) und
**verifiziert ihn gegen die mitveröffentlichte `.sha256`**. Stimmt die
Prüfsumme nicht, wird das Update abgebrochen. Vor dem Ausführen wird
zusätzlich die Authenticode-Signatur gegen den gepinnten Thumbprint geprüft.
Auf macOS (ad-hoc-Signatur ohne pinbare Identität) ist die Prüfsumme der
einzige Anker und deshalb dort **Pflicht** (fail closed).

## Upgrade auf ein echtes Zertifikat (OV/EV)

1. OV/EV-Code-Signing-Zertifikat als `.pfx` beziehen.
2. Die beiden Secrets ersetzen und den neuen Thumbprint zusätzlich pinnen.
3. Fertig – `sign.ps1` und der Workflow bleiben unverändert.
