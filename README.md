# PcDog

PcDog przygotowuje Raspberry Pi Zero 2 W do przyszłej roli kontrolera komputera.
Pierwsza faza zapewnia powtarzalny, bezpieczny fundament systemowy; nie steruje
jeszcze GPIO ani komputerem.

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
