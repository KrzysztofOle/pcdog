# USB service channel SSH dla PcDog

**Status: NOT VERIFIED / PHYSICAL USB HOST TEST REQUIRED**

Ten dokument opisuje projekt i przygotowanie etapu 1 stałego kanału
administracyjnego SSH przez USB. Lokalny test ConfigFS bez hosta USB przeszedł,
ale USB-SSH obecnie **nie jest zweryfikowany**; żaden opis poniżej nie oznacza
potwierdzonego działania z fizycznym hostem.

## Zakres i stan faktyczny

Pierwsza inspekcja była odczytowa. Następnie 5 września 2026 wykonano
kontrolowaną naprawę `ifname` i test lokalny przy odłączonym kablu USB hosta.
Nie wykonywano rebootu ani operacji GPIO/POWER/RESET.

Potwierdzony stan PcDog1:

- Raspberry Pi Zero 2 W Rev 1.0;
- Raspberry Pi OS / Debian 13.5 (trixie), architektura `aarch64`;
- kernel `6.18.34+rpt-rpi-v8`;
- aktywne pliki boot to `/boot/firmware/config.txt` i
  `/boot/firmware/cmdline.txt`;
- aktywny jest NetworkManager 1.52.1; `wlan0` ma adres `192.168.7.162/22`,
  bramę `192.168.7.1` i DNS `192.168.7.1`;
- `ssh.service` jest `enabled` i `active`, nasłuchuje na `0.0.0.0:22` oraz
  `[::]:22`;
- kernel zawiera `CONFIG_USB_DWC2=y`, ConfigFS oraz moduły
  `libcomposite`, `usb_f_ecm`, `usb_f_rndis` i `usb_f_ncm`;
- ConfigFS jest zamontowany, a `pcdog-usb-gadget.service` tworzy aktywny gadget
  ConfigFS zbindowany do UDC `3f980000.usb`; przy odłączonym hoście stan UDC to
  `not attached`, a `usb0` nie ma carrier;
- nie znaleziono aktywnych usług nftables, ufw ani firewalld; narzędzia
  `nft`/`iptables` nie są zainstalowane, więc pełna zawartość reguł netfilter
  nie została potwierdzona;
- `pcdog.service` jest `enabled` i `active`, lecz kanał USB ma być od niego
  niezależny;
- pakiet `rpi-usb-gadget` 1.0.6 jest zainstalowany, ale jego usługa jest
  wyłączona i gadget nie jest aktywny.

## Kontrolowany lokalny test bez hosta USB

Test z 5 września 2026 wykonano przy stale odłączonym kablu między portem
`USB` Pi a Makiem. Poprawka zapisu `ifname` używa literalnego wzorca `usb%d`,
którego wymaga aktualny kernel, zamiast niedozwolonej stałej nazwy `usb0`.

Potwierdzono lokalnie:

- cleanup usuwa częściowy gadget i `usb0`, bez zmiany Wi-Fi, DNS, default route
  ani `ip_forward`;
- start tworzy funkcję ECM, symlink konfiguracji, `usb0` i bind do
  `3f980000.usb`;
- `dev_addr=02:50:43:44:4f:47` i `host_addr=02:50:43:44:4f:48`;
- po aktywacji profilu `pcdog-usb0` Pi ma `172.23.254.1/30`, bez bramy i bez
  default route przez USB;
- `pcdog-usb-dhcp.service` działa, nie uruchamia DNS i wiąże sockety wyłącznie
  z `usb0`; bez hosta nie powstał lease;
- `sshd` nadal nasłuchuje na `0.0.0.0:22` i `[::]:22`, a SSH przez Wi-Fi oraz
  `pcdog.service` pozostają aktywne;
- pojedynczy cykl `stop → cleanup → start` przeszedł bez błędów ConfigFS,
  ECM ani DWC2.

NetworkManager nie autoaktywował profilu Ethernet przy braku carrier; w teście
profil został aktywowany jawnie przez uprzywilejowane `nmcli`. Nie jest to test
zachowania autoconnect po fizycznym podłączeniu hosta.

Nie zweryfikowano enumeracji USB, DHCP po stronie hosta, ruchu Ethernet ani SSH
przez fizyczny kabel. Te elementy pozostają wymaganym kolejnym testem.

## Projektowana architektura

Preferowany jest **ConfigFS + `libcomposite`**, uruchamiany przez osobną
systemd unit infrastruktury systemowej. Usługa powinna wymagać tylko lokalnego
systemu plików, ConfigFS i dostępności kontrolera DWC2; nie może wymagać
`wlan0`, Internetu ani `pcdog.service`.

Gadget powinien udostępniać Ethernet:

- CDC ECM dla macOS i Linux;
- RNDIS dla Windows 10/11;
- NCM nie jest wymagany w pierwszej wersji;
- ECM i RNDIS należy traktować jako alternatywne konfiguracje USB, nie jako
  przypadkowe dwa interfejsy routowane jednocześnie.

`usb0` ma być tworzony automatycznie po każdym starcie i ponownym podłączeniu
kabla. Planowana adresacja punkt-punkt:

```text
Raspberry Pi: 172.23.254.1/30
PC:          172.23.254.2/30
```

DHCP ma działać wyłącznie na `usb0`, aby komputer otrzymywał `172.23.254.2`.
Profil NetworkManager `pcdog-usb0` nie ustawia `ipv4.dns` ani
`ipv4.dns-priority`; pozostawienie priorytetu domyślnej wartości `0` oznacza,
że kanał USB nie konkuruje z DNS normalnego interfejsu, np. `wlan0`.
Serwer DHCP nie powinien przekazywać bramy ani DNS. Nie wolno włączać
domyślnej trasy, `ip_forward`, NAT ani Internet Connection Sharing (ICS).
Przewidywana komenda użytkownika:

```bash
ssh krzysztof@172.23.254.1
```

Utrata lub błędna konfiguracja `wlan0` nie może usuwać adresu `usb0`, zatrzymywać
SSH ani powodować routingu PC przez Wi-Fi. Start Pi bez podłączonego PC ma
kończyć się normalnie; po podłączeniu gadget ma ponownie się enumerować.

## Decyzje i rekomendacje niezweryfikowane fizycznie

Powyższa konfiguracja przeszła test lokalny bez hosta. Nie potwierdzono jeszcze
enumeracji na rzeczywistym kablu, nazw interfejsów po stronie hosta, działania
DHCP ani SSH na żadnym z trzech systemów.

Wariant legacy `g_ether` jest prosty. Oficjalny pakiet Raspberry Pi dobiera
ECM dla macOS/Linux i RNDIS dla Windows, lecz zawiera mechanizm ICS/routingu;
dlatego nie jest domyślną rekomendacją dla izolowanego kanału PcDog.

ConfigFS jest opisany przez [dokumentację kernela Linux](https://docs.kernel.org/usb/gadget_configfs.html).
Możliwości OTG Zero 2 W i użycie portu `USB` opisuje [Raspberry Pi](https://www.raspberrypi.com/news/usb-gadget-mode-in-raspberry-pi-os-ssh-over-usb/).
Obsługę RNDIS w Windows opisuje [Microsoft Learn](https://learn.microsoft.com/en-us/windows-hardware/drivers/network/remote-ndis--rndis-2).

## Przygotowanie etapu 1

Odtwarzalne artefakty są w repozytorium: skrypt ConfigFS
`runtime/pcdog-usb-gadget.sh`, unity `pcdog-usb-gadget.service` i
`pcdog-usb-dhcp.service`, profil NetworkManager `config/pcdog-usb0.nmconnection`
oraz konfiguracja `config/usb-dhcp.conf`. Instaluje je wyłącznie dedykowany
skrypt:

```bash
sudo ./scripts/install-usb-service-channel.sh
```

Skrypt zapisuje kopię aktywnego `/boot/firmware/config.txt` w
`/var/lib/pcdog/usb-service-channel-backup/config.txt.pre-usb-service`, dodaje
`dtoverlay=dwc2,dr_mode=peripheral` i włącza unity na kolejny boot. Nie startuje
gadgetu, DHCP ani NetworkManager w bieżącym boocie. Nie zmienia `cmdline.txt`,
Wi-Fi, SSH, domyślnej trasy, DNS, NAT ani `ip_forward`.

Pierwsza konfiguracja aktywuje wyłącznie CDC ECM. Tworzy jedno `usb0`, używa
stałych lokalnie administrowanych MAC i przydziela wyłącznie
`172.23.254.2/30`; dnsmasq nie uruchamia DNS (`port=0`) ani nie przekazuje
bramy lub serwerów DNS. Wariant Windows/RNDIS pozostaje przyszłym rozszerzeniem
funkcji gadgetu, bez zmiany warstwy systemd, NetworkManager czy DHCP.

Nie należy dodawać ujemnego `dns-priority` do profilu USB bez własnego serwera
DNS. NetworkManager może wtedy wykluczyć DNS z innych aktywnych interfejsów
podczas ponownego przeliczania resolvera, mimo że USB samo DNS-u nie dostarcza.
DNS i dostęp do Internetu pozostają odpowiedzialnością zwykłego interfejsu
sieciowego, np. `wlan0`.

Kontrola bez zmian:

```bash
sudo ./scripts/install-usb-service-channel.sh --check
```

## Plan wdrożenia

1. Zachować działające SSH po Wi-Fi i przygotować kopie zmienianych plików.
2. Przygotować unit ConfigFS, profil NetworkManager `usb0` i DHCP, bez ich
   uruchamiania w bieżącym boocie.
3. Dodać konfigurację DWC2 oraz moduły, zachowując możliwość wycofania każdej
   zmiany.
4. Pierwszy test wykonać przy równolegle działającym SSH przez Wi-Fi.
5. Przetestować macOS, Windows 10/11 i Linux: enumerację, adresy, ping, SSH,
   odłączenie/podłączenie kabla, restart PC i brak Wi-Fi.
6. Reboot Pi wykonać dopiero po wyraźnym zatwierdzeniu przez Human Authority.
7. Po teście sprawdzić brak bramy, DNS, tras domyślnych, forwardingu, NAT i ICS.
8. Dopiero wtedy oznaczyć kanał jako serwisowy.

## Rollback

Przed wdrożeniem zapisać kopie i sumy kontrolne `config.txt`, `cmdline.txt`,
unitów systemd, profili NetworkManager i konfiguracji DHCP. Wycofanie obejmuje
zatrzymanie/wyłączenie wyłącznie nowej usługi, odpięcie gadgetu od UDC, usunięcie
jej konfiguracji oraz przywrócenie kopii plików. Nie usuwać ani nie restartować
`pcdog.service`; podstawowym kanałem awaryjnym pozostaje SSH przez Wi-Fi.

Przez działające SSH po Wi-Fi wykonaj:

```bash
sudo systemctl disable --now pcdog-usb-dhcp.service pcdog-usb-gadget.service
sudo rm -f /etc/systemd/system/pcdog-usb-{gadget,dhcp}.service \
  /usr/local/lib/pcdog/pcdog-usb-gadget /etc/pcdog/usb-dhcp.conf \
  /etc/NetworkManager/system-connections/pcdog-usb0.nmconnection \
  /var/lib/pcdog/usb-dhcp.leases
sudo install -o root -g root -m 755 \
  /var/lib/pcdog/usb-service-channel-backup/config.txt.pre-usb-service \
  /boot/firmware/config.txt
sudo systemctl daemon-reload
```

Po wycofaniu overlay wymaga zatwierdzonego rebootu, aby zniknął z uruchomionego
jądra. Usunięcie pakietów nie jest wymagane: etap używa już zainstalowanego
`dnsmasq-base`.

## Kryteria akceptacji

- po restarcie Pi gadget tworzy `usb0` bez Wi-Fi i bez PC;
- po podłączeniu PC macOS/Linux używają ECM, a Windows RNDIS;
- Pi ma `172.23.254.1`, PC otrzymuje `172.23.254.2` przez DHCP;
- `ssh krzysztof@172.23.254.1` działa po każdym ponownym podłączeniu;
- brak Wi-Fi nie wpływa na USB-SSH;
- `usb0` nie instaluje bramy/DNS ani trasy domyślnej i nie uruchamia NAT,
  forwardingu lub ICS;
- bieżące SSH po Wi-Fi pozostaje dostępne podczas pierwszego wdrożenia;
- rollback przywraca poprzedni stan bez utraty `pcdog.service`.
