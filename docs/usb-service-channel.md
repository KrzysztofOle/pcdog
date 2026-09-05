# USB Service Channel dla PcDog1 — Windows/RNDIS

**Status: Windows/RNDIS verified on PcDog1.** Ten etap celowo nie obejmuje
ECM ani macOS/Linux.

Kanał USB jest izolowanym kanałem serwisowym do administracji PcDog1, niezależnym
od Wi-Fi i `pcdog.service`. Nie jest trasą do Internetu, nie używa NAT, Internet
Connection Sharing (ICS), `ip_forward` ani konfiguracji Windows.

## Zweryfikowany kontrakt Windows

Po podłączeniu PcDog1 do Windows gadget jest wykrywany jako **Remote NDIS
Compatible Device** z natywnym sterownikiem Microsoft `rndiscmp.inf` i adapterem
`Ethernet 2`.

```text
PcDog1 usb0:       172.23.254.1/30
Windows przez DHCP: 172.23.254.2/30
```

DHCP dla `usb0` nie przekazuje bramy ani DNS. W szczególności
`dhcp-option=option:router` wysyła pustą opcję Router, dzięki czemu Windows nie
instaluje default route przez USB. `port=0` w `dnsmasq` wyłącza DNS dla tego
kanału. Zwykła sieć hosta (np. Wi-Fi) zachowuje własną bramę, DNS oraz dostęp do
Internetu.

Przez USB działają `ping`, TCP/22 i SSH do `172.23.254.1`; równocześnie
zweryfikowano Wi-Fi, rozwiązywanie DNS i HTTPS Internetu na hoście Windows.

## Konfiguracja gadgetu

`runtime/pcdog-usb-gadget.sh` tworzy dokładnie jedną funkcję
`rndis.usb0` w jednej konfiguracji ConfigFS `c.1`. Nie dodaje ECM jako drugiej
funkcji ani konfiguracji.

Funkcja RNDIS używa stałych lokalnie administrowanych MAC oraz literalnego
wzorca `usb%d`, z którego kernel tworzy `usb0`. Jej IAD ma dokładnie:

```text
class=ef
subclass=04
protocol=01
```

Wartości IAD są zapisywane bez prefiksu `0x`. RNDIS-T04 wykazał, że w tym
środowisku zapis `0xef`, `0x04` lub `0x01` był interpretowany jako `00`.

Gadget wystawia Microsoft OS descriptors powiązane z konfiguracją `c.1`:

```text
use=1
qw_sign=MSFT100
b_vendor_code=0xcd
compatible_id=RNDIS
```

Powiązanie `os_desc/c.1 -> configs/c.1` jest wymagane, aby Windows odczytał te
deskryptory dla aktywnej konfiguracji i przypisał natywny sterownik RNDIS.

## Instalacja i idempotencja

Artefakty ConfigFS, unitów systemd, profilu NetworkManager i konfiguracji DHCP
instaluje wyłącznie:

```bash
sudo ./scripts/install-usb-service-channel.sh
```

Skrypt zapisuje kopię aktywnego `/boot/firmware/config.txt`, dodaje tylko raz
`dtoverlay=dwc2,dr_mode=peripheral`, aktualizuje pliki docelowe i włącza unity
na następny boot. Nie uruchamia gadgetu, DHCP ani NetworkManager w bieżącym
boocie, nie zmienia `cmdline.txt`, Wi-Fi, SSH, routingu, DNS, NAT ani GPIO.
Można go uruchomić ponownie; kopia pliku boot nie jest nadpisywana.

Kontrola bez zmian:

```bash
sudo ./scripts/install-usb-service-channel.sh --check
```

Statyczny test regresji kontraktów repozytorium (nie dotyka runtime PcDog1):

```bash
bash tests/usb-rndis-service-channel-contract.sh
```

Profil NetworkManager `pcdog-usb0` ustawia tylko `172.23.254.1/30`, ma
`never-default=true` i nie definiuje DNS. `dnsmasq` wiąże się wyłącznie z
`usb0` i przydziela wyłącznie `172.23.254.2/30`.

## Wyniki eksperymentów

### RNDIS-T04 — PASS

Na Windows potwierdzono enumerację Remote NDIS Compatible Device, sterownik
`rndiscmp.inf`, `Ethernet 2`, adresację `/30`, link UP oraz `ping`, TCP/22 i
SSH przez USB. Na PcDog1 potwierdzono `rndis.usb0`, IAD `ef/04/01`, `usb0`
`172.23.254.1/30` i carrier/link UP. Potwierdzono także Microsoft OS descriptors
oraz ich powiązanie z konfiguracją.

### ROUTE-T02 — PASS

Windows otrzymał przez DHCP `172.23.254.2/30` bez gateway, DNS i default route
przez USB. USB Service Channel obsłużył `ping`, TCP/22 i SSH, nie zakłócając
Wi-Fi, DNS ani HTTPS Internetu. Poprawką, która utrwala brak bramy, jest
`dhcp-option=option:router`.

Zakres tych wyników nie obejmuje odtworzenia konfiguracji po reboocie PcDog1.

## Rollback

Przez działające SSH po Wi-Fi można wyłączyć tylko USB Service Channel i
przywrócić zapisaną kopię pliku boot:

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

Usunięcie aktywnego overlay wymaga osobno zatwierdzonego rebootu.

## Następny eksperyment: WINDOWS-RNDIS-REBOOT-T01

Celem jest wyłącznie sprawdzenie, czy po reboocie PcDog1 instalacja odtwarza
ten sam Windows/RNDIS Service Channel: `rndis.usb0`, IAD `ef/04/01`, Microsoft
OS descriptors, `172.23.254.1/30` ↔ `172.23.254.2/30`, brak USB gateway/DNS/
default route oraz działające `ping`, TCP/22 i SSH bez naruszenia Wi-Fi.
Eksperyment wymaga osobnego zatwierdzenia rebootu i nie jest wykonywany w tym
etapie.
