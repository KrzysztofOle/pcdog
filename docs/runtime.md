# Runtime PcDog i usługa systemd

Instalator runtime instaluje `pcdog.service` jako Web API i Web Panel,
`pcdog-system-agent.service` jako oddzielony agent statusowy,
`pcdog-hardware-agent.service` jako agent wejść GPIO oraz
`pcdog-network-agent.service` jako wąsko ograniczony agent Wi-Fi. Panel nie
używa GPIO i nie steruje komputerem; nie zawiera POWER, RESET ani Control API.

## Czysty model domenowy i State Engine

Repozytorium zawiera także pakiet Python `pcdog_runtime`, uruchamiany przez
`pcdog.service`. Definiuje on `PC_STATE` (`OFF`, `ON`,
`UNKNOWN`), `PCDOG_STATE` (`HEALTHY`, `DEGRADED`, `ERROR`), nietrwały snapshot,
zdarzenia domenowe oraz State Engine.

State Engine przyjmuje tylko abstrakcyjne `InputReading`: wiarygodny POWER LED
wyznacza `PC_STATE`, a HDD activity jest przechowywane niezależnie i nigdy samo
nie zmienia stanu PC. Dostępny `FakeInputSource` służy wyłącznie testom i
deterministycznej symulacji.

`InputMonitor` działa z abstrakcyjnym `InputSource`; produkcyjnie korzysta z
klienta hardware-agenta.
Oddziela czasowy debounce POWER LED oraz politykę hold dla impulsów HDD od
interpretacji domenowej w State Engine.

IMPLEMENTED (software): `pcdog-hardware-agent.service` działa jako `root:pcdog`
i odczytuje GPIO19 (HDD LED) oraz GPIO20 (POWER LED) przez `gpioget`. Linux
GPIO character-device wymaga deskryptora `O_RDWR` także dla żądania wejścia;
dostęp unitu pozostaje ograniczony do `/dev/gpiochip0`. `pcdog.service`
zachowuje `PrivateDevices=yes`, nie należy do grupy GPIO i odbiera dane przez
socket. Błąd GPIO lub brak agenta jest mapowany na niewiarygodny `UNKNOWN`, a
nie `OFF`.

Socket przyjmuje zawsze tylko `status` i `read_inputs`, a przy jawnie włączonym
sterowaniu dodatkowo wyłącznie `pulse_power` oraz `pulse_reset`. Nie ma API z
numerem GPIO, `set_gpio`, utrzymania output przez klienta ani nieograniczonego
czasu. Agent sam utrzymuje pojedynczy impuls 50–500 ms (domyślnie 200 ms),
zwraca linię do stanu nieaktywnego i zwalnia ją do INPUT; wyjątek, timeout albo
zamknięcie IPC nie może przedłużyć impulsu. POWER i RESET są wzajemnie
wykluczone.

Domyślnie usługa nie otrzymuje `PCDOG_CONTROL_POLARITY`, dlatego GPIO16 i
GPIO17 pozostają INPUT, a oba polecenia impulsu są odrzucone. Plik opcjonalny
`/etc/pcdog/hardware-control.conf` jest wczytywany wyłącznie jako
`EnvironmentFile` systemd i musi mieć jedną potwierdzoną wartość
`PCDOG_CONTROL_POLARITY=active-high` albo `active-low`. Brak potwierdzonej
polaryzacji jest warunkiem bezwzględnego zakazu live testu. Szczegóły mapowania
i procedury znajdują się w [dokumentacji GPIO](gpio-mapping.md).

`EventStore` używa standardowej biblioteki `sqlite3`: utrzymuje append-only
`events` i restart-safe `current_state`, zapisywane atomowo w jednej transakcji.
Schemat ma minimalne wersjonowanie, a baza korzysta z WAL i `busy_timeout`.
Kod nie narzuca ścieżki pliku; docelową lokalizacją produkcyjną pozostaje
`/var/lib/pcdog`. Runtime cyklicznie przekazuje odczyty do `InputMonitor` i
zapisuje wyniki atomowo do tej samej bazy SQLite, z której API odczytuje stan
i historię. Restart runtime nie usuwa bazy ani historii.

## Web API v1

Pakiet `pcdog_runtime.web_api` udostępnia odczytowe endpointy danych:

- `/api/v1/health` zwraca np. `{ "status": "HEALTHY" }`;
- `/api/v1/state` zwraca snapshot; przy braku snapshotu zwraca stabilne `404`
  z kodem `STATE_UNAVAILABLE`, nigdy fałszywe `OFF`;
- `/api/v1/events?limit=50&after_id=123` zwraca eventy rosnąco po ID.
- `/api/v1/system` zwraca wyłącznie gotowość oddzielnego system-agenta.

Odpowiedzi są JSON UTF-8, enumy są stringami, a timestampy mają sufiks `Z`.
Limit eventów ma konfigurowalne maksimum. Dane poza health wymagają sesji
zalogowanego administratora. `POST /api/v1/session` i
`DELETE /api/v1/session` służą wyłącznie do logowania i wylogowania.
Nie istnieją endpointy POWER, RESET ani Control API. Testy wiążą serwer tylko
z loopback i portem efemerycznym; API nie steruje sprzętem ani GPIO.

## Web Panel — etap Wi-Fi

Przed odczytaniem stanu, historii i sieci użytkownik musi zalogować się
lokalnym hasłem administratora. Endpoint `GET /api/v1/health` pozostaje
niechroniony wyłącznie dla istniejącego health check usługi; nie zawiera danych
PC, zdarzeń, interfejsów ani konfiguracji sieci.

Hasło ustawia się na Raspberry Pi po instalacji, poza repozytorium:

```bash
sudo /opt/pcdog/bin/pcdog-web-auth set-password
sudo systemctl restart pcdog
```

Narzędzie pyta o hasło interaktywnie, wymaga co najmniej 12 znaków i zapisuje
wyłącznie rekord `scrypt` w `/etc/pcdog/web-auth.json` o uprawnieniach
`root:pcdog 0640`. Nie dodawaj pliku do Git ani nie przekazuj hasła w
argumentach polecenia. Brak konfiguracji blokuje panel kodem
`AUTH_NOT_CONFIGURED`, ale nie blokuje health check.

Po poprawnym logowaniu serwer tworzy losową sesję pamięciową ważną 30 minut.
Cookie ma `HttpOnly`, `SameSite=Strict` i ograniczenie do ścieżki `/`;
restart usługi unieważnia wszystkie sesje. Wylogowanie wymaga tokenu CSRF i
zgodnego nagłówka `Origin`. Pięć nieudanych prób z jednego adresu w ciągu
10 minut czasowo blokuje kolejne logowanie z tego adresu.
W obecnym HTTP nie ma flagi `Secure`: panel jest przeznaczony wyłącznie do
zaufanej sieci prywatnej/ZeroTier i nie może być wystawiony do Internetu.

Panel ma cztery widoki z adresami `#status`, `#history`, `#network`
i `#settings`. Na telefonie nawigacja znajduje się u dołu ekranu; historia
to karty ostatnich 25 zdarzeń, od najnowszego, bez przewijania poziomego.
Nawigacja obsługuje historię przeglądarki, klawiaturę i oznaczenie bieżącej strony.
Ustawienia pokazują także gotowość oddzielnego system-agenta. Nadal obsługuje
on wyłącznie lokalne żądanie `status`, a operacje zasilania są wyłączone. Nie
dodano restartu, wyłączania ani sterowania PC.

`GET /api/v1/network` odczytuje interfejsy, stan, nazwę profilu i adresy IP
przez ograniczone czasem (2 s) `nmcli device show`. Nie skanuje sieci,
nie czyta sekretów ani nie modyfikuje profili. Brak nmcli, odmowa dostępu
lub timeout daje `UNAVAILABLE`, a nie informację o rozłączeniu.
Nazwa profilu nie jest traktowana jako SSID. Nie są jeszcze raportowane
siła sygnału, uptime ani potwierdzony stan połączenia ZeroTier.
Endpoint nie zmienia uprawnień usługi i, podobnie jak pozostałe dane panelu,
wymaga zalogowanej sesji.

Widok **Sieć** umożliwia zmianę Wi-Fi przez osobny agent. `GET /api/v1/wifi`
zwraca skan wyłącznie zabezpieczonych sieci: SSID, BSSID, rodzaj zabezpieczeń i
sygnał. `GET /api/v1/wifi/connection` zwraca ulotny stan ostatniej operacji,
a `POST /api/v1/wifi/connection` przyjmuje wyłącznie SSID, opcjonalny BSSID i
hasło w JSON body. Zmiana wymaga sesji, CSRF i zgodnego `Origin`; nie przyjmuje
interfejsu, profilu ani dowolnych argumentów wykonawczych.

Hasło Wi-Fi nie może pojawić się w URL, odpowiedzi, logach ani wyniku joba.
Network-agent uruchamia `nmcli` bez powłoki. Tworzy kandydatowy profil wyłącznie
w pamięci NetworkManagera (`save no`), a sekret podaje przez stdin `nmcli --ask`;
nigdy przez argv ani plik trwały. Dopuszcza jeden aktywny job i przechowuje wynik
tylko w pamięci, maksymalnie przez 5 minut. Oznacza to, że nowa konfiguracja nie
przetrwa restartu Raspberry Pi — trwałe zapisywanie poświadczeń wymaga osobnego,
świadomie zatwierdzonego etapu.

Przed próbą połączenia agent zapamiętuje aktywny profil Wi-Fi. Sukces wymaga
potwierdzenia aktywnego SSID/BSSID przez NetworkManager i adresu IPv4. Błędne
hasło, błąd lub timeout NetworkManagera albo brak potwierdzenia uruchamiają
próbę przywrócenia poprzedniego profilu; istniejące profile nie są usuwane.
Telefon lub komputer może wymagać połączenia z nową siecią i ponownego otwarcia
panelu. USB pozostaje kanałem recovery, bez założenia obsługi USB Ethernet przez
telefon.

Ten sam testowalny serwer HTTP udostępnia minimalny panel statyczny pod `GET /`
oraz jego lokalne zasoby pod `/static/pcdog-panel.css` i
`/static/pcdog-panel.js`. Panel nie wymaga Node.js, procesu build, CDN ani
zewnętrznej sieci. Jest wyłącznie klientem `GET /api/v1/health`,
`GET /api/v1/session`, `GET /api/v1/state`, `GET /api/v1/network`,
`GET /api/v1/system`, `GET /api/v1/wifi`, `GET /api/v1/wifi/connection` i
`GET /api/v1/events?limit=N`;
logowanie używa `POST /api/v1/session`, a wylogowanie `DELETE /api/v1/session`.
Nie ma kontrolek administracyjnych ani
endpointów POWER, RESET czy Control API.

Domyślnie panel odświeża dane co 5 sekund (stała `pollingIntervalMs` w pliku
JavaScript), nie rozpoczynając drugiego odświeżenia, gdy poprzednie jeszcze
trwa. Timestampy API w UTC są wyświetlane spójnie jako czas lokalny przeglądarki.
Brak snapshotu (`STATE_UNAVAILABLE`) albo błąd odczytu stanu jest pokazywany jako
`UNKNOWN` / „brak danych”, nigdy jako `OFF`. Wyniki endpointów są obsługiwane
niezależnie: niedostępna historia nie ukrywa dostępnego stanu PC.

## Wdrożenie runtime na PcDog1

`pcdog.service` uruchamia `pcdog_runtime.read_only_runtime` pod Pythonem 3 bez
`pip` ani zewnętrznych zależności. Produkcyjny bind IPv4 to `0.0.0.0:8080`; nie
jest tworzony wildcard IPv6. Baza znajduje się w
`/var/lib/pcdog-runtime/pcdog.sqlite3`. Jest to bezpieczniejszy wariant niż
preferowany podkatalog `/var/lib/pcdog/runtime`: istniejący rodzic
`/var/lib/pcdog` ma `root:root 0750`, więc udostępnienie jego podkatalogu
użytkownikowi usługi wymagałoby osłabienia ochrony artefaktów USB/DHCP.
`StateDirectory=pcdog-runtime` tworzy wydzielony katalog `pcdog:pcdog 0750`,
gdzie SQLite może tworzyć pliki WAL/SHM bez dostępu do pozostałych danych.

Przy `ProtectSystem=strict` katalog skonfigurowany przez `StateDirectory` jest
jedyną ścieżką zapisu usługi; `PrivateDevices=yes` i pozostały hardening
pozostają aktywne. Do wdrożenia samego runtime należy używać
`sudo ./scripts/install-runtime.sh`, a nie pełnego bootstrapu, aby nie dotykać
niepowiązanych komponentów systemowych.

`pcdog-system-agent.service` działa jako `root:pcdog`, ale w tym etapie nie
uruchamia żadnych poleceń systemowych. Jego socket
`/run/pcdog-system-agent/agent.sock` ma grupowy dostęp wyłącznie dla procesu
`pcdog` i przyjmuje krótki, zamknięty protokół JSON. Jedyną dozwoloną operacją
jest `status`; próby restartu i wyłączenia są odrzucane. Jest to fundament do
późniejszego, osobno zatwierdzonego projektu kontroli zasilania, a nie możliwość
wykonania tych akcji.

`pcdog-network-agent.service` jest odrębnym procesem `root:pcdog`, bez GPIO i
funkcji zasilania. Socket `/run/pcdog-network-agent/agent.sock` ma tryb `0660`
w katalogu runtime `0750` i jest przeznaczony wyłącznie dla `pcdog`. Na Linuksie
agent dodatkowo sprawdza UID klienta przez `SO_PEERCRED`. Zamknięty protokół JSON
ma dokładnie `list_wifi`, `connect_wifi` i `connection_status`. Rzeczywistą
zgodność `nmcli --ask` z docelową wersją NetworkManagera należy potwierdzić
dopiero kontrolowanym live testem z dostępnym recovery.

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
