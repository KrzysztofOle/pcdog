# Kontrolowany test restartu USB PcDog1

Ten test sprawdza automatyczny powrót USB ECM, DHCP i SSH po pojedynczym
restarcie PcDog1. Nie uruchamiaj go bez osobnej zgody Krzysztofa. W bieżącej
lokalizacji Wi-Fi i ZeroTier nie są kanałem odzyskiwania; po restarcie USB może
pozostać jedynym praktycznym kanałem serwisowym.

## Wymagania przed testem

- Bieżące SSH przez USB działa i wskazuje `PcDog1`.
- Mac ma wpis host key dla `172.23.254.1`; skrypt odmawia pracy bez niego.
- Na Pi działa persistent journal. Konfiguracja z
  `config/pcdog-journald.conf` powinna znajdować się w
  `/etc/systemd/journald.conf.d/99-pcdog-persistent.conf`.
- `journalctl --list-boots` wskazuje bieżący boot, a
  `journalctl --directory=/var/log/journal --list-boots` również zawiera jego
  identyfikator. Wykonaj `journalctl --flush` przed testem, jeżeli journal nie
  został jeszcze utrwalony.
- Mac używa DHCP na `PcDog USB ECM service`, ma `172.23.254.2/30`, a brama
  domyślna nadal prowadzi przez Wi-Fi.
- Przygotuj Terminal A dla obserwatora i Terminal B do wydania pojedynczego
  polecenia restartu.

## Wykonanie

1. W Terminalu A uruchom obserwatora i zachowaj zapis:

   ```bash
   ./scripts/mac-usb-reboot-watch.sh 300 | tee ~/pcdog-usb-reboot-watch.log
   ```

   Skrypt tylko odczytuje stan. Sprawdza host key i SSH przed testem, po czym
   uzbraja się. Czeka na zanik urządzenia USB lub SSH, a następnie przez maks.
   300 sekund raportuje enumerację USB, interfejs ECM, carrier, DHCP, IPv4, ARP,
   ping, TCP/22 i SSH. Sukces wymaga trzech kolejnych próbek SSH, które zwracają
   `PcDog1`.

2. Dopiero po osobnej zgodzie, z Terminala B wydaj dokładnie jeden restart:

   ```bash
   ssh -o BatchMode=yes krzysztof@172.23.254.1 'sudo systemctl reboot'
   ```

3. Pozostaw Terminal A aktywny do `PASS` albo `TIMEOUT`. Po `PASS` sprawdź na
   Macu, że brama domyślna nadal wskazuje Wi-Fi. Na Pi, przez odzyskane USB,
   odczytaj `journalctl --list-boots` i `journalctl -b -1`.

## STOP i odzyskanie dostępu

Po `TIMEOUT` nie ponawiaj restartu, nie zmieniaj adresów ani profili i nie
restartuj usług USB. Zachowaj log obserwatora. Z Maca można dalej wykonać tylko
odczytowe rozpoznanie: `ioreg -p IOUSB -l -w0`, `system_profiler SPUSBDataType`,
`networksetup -getinfo 'PcDog USB ECM service'`, `ifconfig en12`,
`ipconfig getpacket en12`, `arp -n 172.23.254.1`, ograniczony `ping` i `nc` na
TCP/22. Te czynności rozróżnią brak enumeracji, brak ECM, brak DHCP i brak
usługi SSH, ale same nie naprawią Pi.

Jeżeli SSH nie wróci, z Maca nie ma zdalnego kanału naprawy w tej lokalizacji.
Zatrzymaj test. Odzyskanie wymaga dostępu lokalnego do konsoli Pi albo
zapewnienia przez operatora innej dostępnej sieci/ścieżki serwisowej. Nie
odłączaj kabla USB jako pierwszego kroku: w tej konfiguracji może to odciąć
zasilanie PcDog1.
