# Walidacja bootstrapu na sprzęcie

## Test z 5 września 2026

Commit `29aa57c` został rzeczywiście zweryfikowany na urządzeniu testowym:

- Raspberry Pi Zero 2 W Rev 1.0,
- Raspberry Pi OS Lite 64-bit (Debian 13 „trixie”),
- architektura `aarch64`.

Przed pierwszym uruchomieniem istniały pakiety `ca-certificates` i `curl`,
natomiast nie było `git`, `/etc/pcdog` ani `/var/lib/pcdog`. Preflight przeszedł
bez zmian systemowych. Pierwszy bootstrap zainstalował `git` oraz utworzył:

- `/etc/pcdog` jako `root:root`, tryb `755`,
- `/var/lib/pcdog` jako `root:root`, tryb `750`.

Drugi, identyczny bootstrap zakończył się powodzeniem bez duplikatów ani zmian
właścicieli i uprawnień. Po kontrolowanym reboocie urządzenie wróciło przez SSH,
a `bootstrap.sh --check` i `verify-installation.sh --check` ponownie przeszły.

Zakres tego wyniku ogranicza się do wymienionej wersji bootstrapu, systemu i
sprzętu. Nie stanowi jeszcze walidacji GPIO, usług PcDog, watchdoga ani
sterowania komputerem.

Ponieważ na obrazie testowym nie było `git`, pierwszy bootstrap otrzymał
niezmienione archiwum commitu w katalogu tymczasowym. Po zakończeniu bootstrapu
normalny klon Git do `~/pcdog` wskazał commit `29aa57c` i był czysty.
