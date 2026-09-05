# PcDog

PcDog przygotowuje Raspberry Pi Zero 2 W do przyszłej roli kontrolera komputera.
Pierwsza faza zapewnia powtarzalny, bezpieczny fundament systemowy; nie steruje
jeszcze GPIO ani komputerem.

## Przygotowanie nowego Raspberry Pi

1. Przygotuj kartę microSD zgodnie z instrukcją [instalacji Raspberry Pi OS](docs/raspberry-pi-os.md).
2. Uruchom Raspberry Pi i połącz się przez SSH kluczem publicznym ustawionym w
   Raspberry Pi Imager, np. `ssh <użytkownik>@<hostname>.local`.
3. Sklonuj repozytorium i uruchom kontrolę środowiska:

   ```bash
   git clone <adres-repozytorium-pcdog>
   cd pcdog
   ./scripts/bootstrap.sh --check
   ```

4. Jeżeli kontrola zakończy się powodzeniem, wykonaj instalację:

   ```bash
   sudo ./scripts/bootstrap.sh
   ```

Bootstrap instaluje wyłącznie minimalne pakiety (`ca-certificates`, `curl`,
`git`) i tworzy `/etc/pcdog` oraz `/var/lib/pcdog`. Można go bezpiecznie
uruchomić ponownie. Szczegóły i ograniczenia są w [dokumentacji systemu](docs/raspberry-pi-os.md).
