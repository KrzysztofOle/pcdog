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

Nie ma trybu `auto` ani `universal`; RNDIS i ECM nigdy nie są wystawiane
jednocześnie. Nowe i istniejące instalacje bez pliku trybu domyślnie używają
`windows`, co zachowuje zweryfikowany Windows baseline.

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
PcDog1; do wykonania przełączenia używaj SSH po Wi-Fi.

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

- `USB-MODE-SWITCH-MAC-T01`: pełny test hosta macOS po przełączeniu na `mac`.
- `USB-MODE-SWITCH-REBOOT-T01`: persistence ostatnio wybranego trybu po reboot.
