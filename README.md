# PcDog

PcDog rozwija Raspberry Pi Zero 2 W jako kontroler i monitor komputera. Aktualna
płytka ma potwierdzone mapowanie GPIO17/18/19/20 oraz przeszła kontrolowany test
obu torów na obwodzie 3.3 V; komputer PC nie był podłączony do POWER ani RESET.
Szczegóły mapowania, granic sterowania i kolejnego etapu są w
[dokumentacji GPIO](docs/gpio-mapping.md), a trwały wynik testu w
[raporcie kontrolowanego testu płytki](docs/gpio-controlled-board-test-2026-09-13.md).

Monitoring używa GPIO19/GPIO20 jako wejść open-collector z pull-up i semantyką
active-low. GPIO17 (POWER CONTROL) oraz GPIO18 (RESET CONTROL) są
ACTIVE-HIGH; w świeżej instalacji runtime ich użycie pozostaje fail-closed bez
jawnej lokalnej konfiguracji polaryzacji. Potwierdzony test płytki nie jest
upoważnieniem do sterowania rzeczywistą płytą główną PC.

## Przygotowanie nowego Raspberry Pi

1. Przygotuj kartę microSD zgodnie z instrukcją [instalacji Raspberry Pi OS](docs/raspberry-pi-os.md).
2. Uruchom Raspberry Pi i połącz się przez SSH kluczem publicznym ustawionym w
   Raspberry Pi Imager, np. `ssh <użytkownik>@<hostname>.local`.
3. Raspberry Pi OS Lite może nie zawierać `git` (tak było na urządzeniu
   testowym). Jeżeli polecenie `git` nie jest dostępne, zainstaluj je jednorazowo:

   ```bash
   sudo apt-get update
   sudo apt-get install --yes git
   ```

4. Sklonuj repozytorium i uruchom kontrolę środowiska:

   ```bash
   git clone <adres-repozytorium-pcdog>
   cd pcdog
   ./scripts/bootstrap.sh --check
   ```

5. Jeżeli kontrola zakończy się powodzeniem, wykonaj instalację:

   ```bash
   sudo ./scripts/bootstrap.sh
   ```

Bootstrap instaluje minimalne pakiety (`ca-certificates`, `curl`, `git`),
tworzy katalogi PcDog i instaluje minimalny runtime jako usługę systemd.
Instaluje też ZeroTier jako opcjonalny, dodatkowy kanał łączności; konfiguracja
Network ID i pierwsze dołączenie są opisane w [dokumentacji ZeroTier](docs/zerotier.md).
Można go bezpiecznie uruchomić ponownie. Szczegóły przygotowania systemu są w
[dokumentacji systemu](docs/raspberry-pi-os.md), a obsługa usługi, logów i
health check jest opisana w [dokumentacji runtime](docs/runtime.md).

## USB service channel SSH dla PcDog

USB Service Channel PcDog1 używa izolowanego połączenia
`172.23.254.1/30` ↔ `172.23.254.2/30`, bez bramy, DNS i default route przez USB.
Obsługuje jawne tryby `windows` (RNDIS) oraz `mac` (ECM), przełączane przez
`sudo pcdog-usb-mode windows` lub `sudo pcdog-usb-mode mac`. Szczegóły i
procedura przełączania są w [dokumentacji USB Service Channel](docs/usb-service-channel.md).

## Ręczna diagnostyka Windows przez USB

V1 ręcznej diagnostyki i kontrolowanego recovery Level 1 jest dostępny jako
`./scripts/windows-network-recovery.py`. Diagnostyka jest tylko odczytowa;
restart jawnie wskazanego adaptera internetowego Windows wymaga `--recover` i
fail-safe chroni adapter USB PcDog. Pełne użycie, statusy oraz procedura
kontrolowanego live testu są w [dokumentacji Windows network recovery](docs/windows-network-recovery.md).

## Bootstrap klucza SSH PcDog → Windows

Jednorazowy, ręczny bootstrap dedykowanego klucza bez hasła w repozytorium opisuje
[instrukcja bootstrapu SSH Windows](docs/windows-ssh-bootstrap.md). Po jego powodzeniu
recovery używa tego klucza w `BatchMode`, bez fallbacku do hasła.
