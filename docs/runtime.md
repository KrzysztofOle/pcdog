# Runtime PcDog i usługa systemd

Bootstrap instaluje minimalny runtime PcDog jako `pcdog.service`. W tej fazie
runtime nie używa GPIO, nie otwiera portów i nie steruje komputerem. Potwierdza
wyłącznie, że proces aplikacji może bezpiecznie działać oraz uruchamiać się po
starcie systemu.

## Czysty model domenowy i State Engine

Repozytorium zawiera także czysty pakiet Python `pcdog_runtime`, który nie jest
jeszcze uruchamiany przez `pcdog.service`. Definiuje on `PC_STATE` (`OFF`, `ON`,
`UNKNOWN`), `PCDOG_STATE` (`HEALTHY`, `DEGRADED`, `ERROR`), nietrwały snapshot,
zdarzenia domenowe oraz State Engine.

State Engine przyjmuje tylko abstrakcyjne `InputReading`: wiarygodny POWER LED
wyznacza `PC_STATE`, a HDD activity jest przechowywane niezależnie i nigdy samo
nie zmienia stanu PC. Dostępny `FakeInputSource` służy wyłącznie testom i
deterministycznej symulacji. Pakiet nie używa GPIO, SQLite, sieci, systemd ani
sprzętu; adapter wejść i persistence będą osobnymi etapami.

`InputMonitor` działa obecnie wyłącznie z abstrakcyjnym/fake `InputSource`.
Oddziela czasowy debounce POWER LED oraz politykę hold dla impulsów HDD od
interpretacji domenowej w State Engine. Nie istnieje jeszcze adapter prawdziwego
GPIO ani żadna interakcja z fizycznymi pinami.

`EventStore` używa standardowej biblioteki `sqlite3`: utrzymuje append-only
`events` i restart-safe `current_state`, zapisywane atomowo w jednej transakcji.
Schemat ma minimalne wersjonowanie, a baza korzysta z WAL i `busy_timeout`.
Kod nie narzuca ścieżki pliku; docelową lokalizacją produkcyjną pozostaje
`/var/lib/pcdog`. W tym etapie nie zmieniono jednak systemd ani uprawnień, nie
zapisano produkcyjnej bazy na PcDog1 i nadal nie istnieje adapter GPIO.

## Read-only Web API v1

Pakiet `pcdog_runtime.web_api` udostępnia testowalny serwer standard library,
który nie jest jeszcze wdrożony na PcDog1. API ma wyłącznie endpointy `GET`:

- `/api/v1/health` zwraca np. `{ "status": "HEALTHY" }`;
- `/api/v1/state` zwraca snapshot; przy braku snapshotu zwraca stabilne `404`
  z kodem `STATE_UNAVAILABLE`, nigdy fałszywe `OFF`;
- `/api/v1/events?limit=50&after_id=123` zwraca eventy rosnąco po ID.

Odpowiedzi są JSON UTF-8, enumy są stringami, a timestampy mają sufiks `Z`.
Limit eventów ma konfigurowalne maksimum. Nie istnieją endpointy POWER, RESET
ani Control API; metody inne niż GET zwracają `405`. Testy wiążą serwer tylko z
loopback i portem efemerycznym. Nie ustalono jeszcze produkcyjnego bindu,
uwierzytelnienia ani wdrożenia systemd; API nie steruje sprzętem ani GPIO.

## Web Panel obserwacyjny

Ten sam testowalny serwer HTTP udostępnia minimalny panel statyczny pod `GET /`
oraz jego lokalne zasoby pod `/static/pcdog-panel.css` i
`/static/pcdog-panel.js`. Panel nie wymaga Node.js, procesu build, CDN ani
zewnętrznej sieci. Jest wyłącznie klientem `GET /api/v1/health`,
`GET /api/v1/state` i `GET /api/v1/events?limit=N`; nie ma kontrolek ani
endpointów POWER, RESET czy Control API.

Domyślnie panel odświeża dane co 5 sekund (stała `pollingIntervalMs` w pliku
JavaScript), nie rozpoczynając drugiego odświeżenia, gdy poprzednie jeszcze
trwa. Timestampy API w UTC są wyświetlane spójnie jako czas lokalny przeglądarki.
Brak snapshotu (`STATE_UNAVAILABLE`) albo błąd odczytu stanu jest pokazywany jako
`UNKNOWN` / „brak danych”, nigdy jako `OFF`. Wyniki endpointów są obsługiwane
niezależnie: niedostępna historia nie ukrywa dostępnego stanu PC.

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
