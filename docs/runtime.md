# Runtime PcDog i usługa systemd

Bootstrap instaluje minimalny runtime PcDog jako `pcdog.service`. W tej fazie
runtime nie używa GPIO, nie otwiera portów i nie steruje komputerem. Potwierdza
wyłącznie, że proces aplikacji może bezpiecznie działać oraz uruchamiać się po
starcie systemu.

## Model uprawnień

Usługa działa jako dedykowany użytkownik systemowy `pcdog`, z grupą `pcdog`,
katalogiem domowym `/nonexistent` i powłoką `nologin`. Nie należy on do grupy
`gpio`. Pliki wykonywalne runtime i jednostka systemd są własnością `root`, więc
sam proces nie może ich modyfikować. Dodatkowe ograniczenia jednostki blokują
dostęp do urządzeń, podnoszenie uprawnień oraz zapisy do systemowych systemów
plików.

## Bootstrap i autostart

Zwykłe uruchomienie:

```bash
sudo ./scripts/bootstrap.sh
```

instaluje runtime w `/opt/pcdog/bin`, jednostkę w
`/etc/systemd/system/pcdog.service`, włącza autostart i uruchamia usługę.
Przy kolejnym bootstrapie usługa nie jest restartowana, jeśli pliki runtime i
jednostka nie uległy zmianie. Po zmianie któregoś z tych plików bootstrap
wykonuje `daemon-reload` (dla unitu) oraz restart usługi.

Tryb:

```bash
./scripts/bootstrap.sh --check
```

pozostaje wyłącznie odczytowy. Zawsze sprawdza preflight; na systemie, na którym
runtime już istnieje, sprawdza także jego pliki, systemd i health check.

## Diagnostyka

Status usługi:

```bash
systemctl status pcdog
systemctl is-enabled pcdog
systemctl is-active pcdog
```

Logi bieżącego startu systemu:

```bash
journalctl -u pcdog -b
```

Lokalny health check nie otwiera portów ani nie używa sieci. Sprawdza, czy
`pcdog.service` jest aktywna, ma główny PID i czy PID należy do zainstalowanego
runtime:

```bash
./scripts/health-check.sh
```

Prawidłowy wynik to `HEALTHY`; każdy problem kończy się `UNHEALTHY` i kodem
niezerowym. Pełną kontrolę instalacji wykonuje:

```bash
./scripts/verify-installation.sh --check
```

Bezpieczny restart samego procesu runtime (nie Raspberry Pi i nie PC):

```bash
sudo systemctl restart pcdog
```

Po zmianie konfiguracji jednostki poza bootstrapem należy wykonać
`sudo systemctl daemon-reload` przed restartem. Standardowo należy jednak
preferować bootstrap, ponieważ weryfikuje zgodność plików z repozytorium.
