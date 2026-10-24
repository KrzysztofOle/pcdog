# USB Service Channel dla PcDog1

USB Service Channel jest izolowanym połączeniem administracyjnym PcDog1. Używa
tej samej adresacji niezależnie od wybranego hosta:

```text
PcDog1 usb0:       172.23.254.1/30
Host przez DHCP:   172.23.254.2/30
```

`dnsmasq` działa wyłącznie na `usb0`, nie oferuje DNS (`port=0`) i wysyła pustą
opcję routera (`dhcp-option=option:router`). USB nie instaluje więc bramy ani
default route i nie używa NAT, ICS ani `ip_forward`. Wi-Fi pozostaje kanałem
administracyjnym podczas każdej zmiany USB.

## Jawny tryb hosta

Obsługiwane są dokładnie dwa trwałe tryby:

| Tryb | Funkcja ConfigFS | Przeznaczenie |
| --- | --- | --- |
| `windows` | `rndis.usb0` | Windows / Remote NDIS Compatible Device |
| `mac` | `ecm.usb0` | macOS / CDC ECM |

Nie ma trybu `auto` ani `universal`; produkcyjna konfiguracja przy starcie
wystawia jedną funkcję zgodną z zapisanym trybem. Nowe i istniejące instalacje
bez pliku trybu domyślnie używają `windows`, co zachowuje zweryfikowany Windows
baseline. Tymczasowy eksperyment z jedną konfiguracją ECM+RNDIS opisuje sekcja
Stage 0A poniżej; nie zmienił produkcyjnego trybu.

Tryb jest przechowywany w `/etc/pcdog/usb-mode.conf` jako `mode=windows` albo
`mode=mac`. Runtime `pcdog-usb-gadget` odczytuje go przy każdym tworzeniu
gadgetu, także po przyszłym reboocie.

```bash
sudo pcdog-usb-mode windows
sudo pcdog-usb-mode mac
pcdog-usb-mode status
```

Zmiana trybu zapisuje konfigurację, kontrolowanie odłącza UDC, usuwa poprzednią
funkcję i linki ConfigFS, buduje jedną właściwą funkcję i ponownie wiąże UDC.
Host USB musi chwilowo ponownie wyenumerować urządzenie. Nie wymaga to rebootu
PcDog1. CLI udostępnia `pcdog usb mode windows|mac`; przed delegacją do tego
samego `pcdog-usb-mode` porównuje trasę aktywnej sesji SSH z rzeczywistą trasą
do hosta USB. Zablokuje zmianę przy SSH przez USB, braku `SSH_CONNECTION` lub
niejednoznacznych trasach. SSH przez Wi-Fi albo ZeroTier może być użyte tylko,
gdy aktywna sesja i routing potwierdzają niezależny kanał; sam profil
ZeroTier nie wystarcza. Nie ma trybu wymuszającego. Bez CLI można wywołać
`sudo pcdog-usb-mode <tryb>` bezpośrednio wyłącznie po niezależnej weryfikacji
trasy administracyjnej.

`status` pokazuje skonfigurowany tryb, aktywną funkcję USB, stan UDC, stan
`usb0` i adres IPv4 PcDog1.

## Kontrakt Windows

Tryb `windows` zachowuje zweryfikowany RNDIS:

- funkcja `rndis.usb0`;
- IAD `class=ef`, `subclass=04`, `protocol=01` — bez prefiksu `0x`;
- Microsoft OS descriptors: `use=1`, `qw_sign=MSFT100`,
  `b_vendor_code=0xcd`, `compatible_id=RNDIS` oraz link `os_desc/c.1`;
- Windows otrzymuje `172.23.254.2/30` bez gateway, DNS i USB default route.

RNDIS-T04, ROUTE-T02 oraz WINDOWS-RNDIS-REBOOT-T01 potwierdziły enumerację
Remote NDIS Compatible Device z `rndiscmp.inf`, DHCP, `ping`, TCP/22, SSH oraz
równoległe Wi-Fi/DNS/HTTPS.

## Kontrakt macOS

Tryb `mac` tworzy wyłącznie `ecm.usb0`, zachowując MAC, `usb%d`, adresację i
izolowany DHCP. Nie tworzy linku `os_desc/c.1` ani nie konfiguruje Microsoft OS
descriptors dla ECM. Poprawność ConfigFS można zweryfikować po Wi-Fi; pełny test
hosta macOS jest osobnym eksperymentem.

## Stage 0A — tymczasowy composite ECM+RNDIS na macOS

Eksperyment wykonano 2026-10-13 na Raspberry Pi Zero 2 W. Celem było
sprawdzenie, czy jedna konfiguracja USB może wystawić ECM i RNDIS razem, tak
aby host wybierał obsługiwaną funkcję bez ręcznej zmiany trwałego trybu PcDog.
Nie wdrożono tego układu produkcyjnie.

### Konfiguracja testowa

- UDC `3f980000.usb`, sterownik `dwc2`; kontroler zgłaszał 7 niezerowych
  endpointów oraz osobny endpoint kontrolny EP0.
- Jedna konfiguracja ConfigFS `c.1`, z funkcjami w kolejności RNDIS, następnie
  ECM.
- `bDeviceClass=0`; funkcja RNDIS miała IAD `class=ef`, `subclass=04`,
  `protocol=01` i Microsoft OS compatible ID `RNDIS` z sub-compatible ID
  `5162001`.
- Linux utworzył osobne interfejsy: `usb0` dla RNDIS i `usb1` dla ECM.
- Testowy ECM używał odrębnej podsieci `172.23.255.0/30`. DHCP przydzielił
  hostowi `172.23.255.2/30` i nie ogłosił opcji routera.

### Wynik macOS

macOS wyenumerował jedno urządzenie high-speed z jedną konfiguracją i
`bDeviceClass=0`. Sterownik `AppleUserECM` obsłużył funkcję ECM jako interfejs
`en12`. Mac nie utworzył osobnego interfejsu sieciowego ani aktywnego sterownika
RNDIS. Nie była potrzebna ręczna instalacja sterownika.

ECM przeszedł DHCP, ping, SSH oraz HTTP Web UI (200). SSH zwrócił hostname
`PcDog1`. Default route Maca pozostał przez Wi-Fi (`192.168.7.1`, `en1`), poza
USB. ZeroTier pozostał `ONLINE` i zapewniał kanał kontrolny przez cały test.

### Rollback i rezultat

Przed zmianą UDC uzbrojono 300-sekundowy timer systemd, który uruchamiał
rollback przez Bash, niezależnie od enumeracji hosta. Po udanym teście rollback
uruchomiono ręcznie przed upływem timera. Usunął testowy gadget i tymczasowy
DHCP, a następnie przywrócił produkcyjny tryb `mac` / ECM. Końcowo aktywne były
`ecm.usb0`, UDC `3f980000.usb`, `usb0=172.23.254.1/30` i produkcyjny DHCP USB;
Mac wrócił do `172.23.254.2/30`. Trwały plik trybu nie był zmieniany.

**Wniosek:** wynik uzasadnia osobny fizyczny test Stage 0B na Windows 11.
Windows Stage 0B nie został wykonany, a przypisanie sterownika RNDIS na Windows
pozostaje niezweryfikowane.

## Instalacja i weryfikacja

Repozytoryjny installer instaluje runtime, komendę `pcdog-usb-mode`, unity,
profil NetworkManager i DHCP. Tworzy domyślny plik trybu tylko, gdy jeszcze nie
istnieje, więc późniejszy upgrade zachowuje wybór hosta.

```bash
sudo ./scripts/install-usb-service-channel.sh
sudo ./scripts/install-usb-service-channel.sh --check
bash tests/usb-mode-switch-contract.sh
```

Installer nie uruchamia gadgetu, DHCP ani NetworkManager w bieżącym boocie.
Do natychmiastowej zmiany trybu służy wyłącznie `pcdog-usb-mode`.

## Następne eksperymenty

- `USB-MODE-SWITCH-MAC-T01`: osobny test pojedynczej funkcji `ecm.usb0` po
  przełączeniu trybu na `mac`.
- `USB-MODE-SWITCH-REBOOT-T01`: persistence ostatnio wybranego trybu po reboot.
- `USB-COMPOSITE-STAGE0B-WIN-T01`: osobny test hosta Windows 11 dla composite
  ECM+RNDIS; Stage 0B nie został rozpoczęty.
