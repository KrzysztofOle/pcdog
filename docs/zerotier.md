# ZeroTier w PcDog

ZeroTier jest opcjonalnym, dodatkowym kanałem zdalnej łączności PcDog. Bootstrap instaluje go oficjalnym instalatorem `https://install.zerotier.com`, włącza i uruchamia `zerotier-one.service`. Nie zmienia Wi-Fi, USB, RNDIS, ECM, DHCP, adresacji `172.23.254.0/30`, tras domyślnych, NAT, bridge ani managed routes. PcDog nie konfiguruje exit node ani routingu między interfejsami.

## Network ID

Network ID nie jest przechowywany w repozytorium. Podaj go jednorazowo jako konfigurację deploymentu (preferowane) albo zapisz lokalnie, z prawami tylko dla roota:

```bash
sudo install --directory --owner=root --group=root --mode=755 /etc/pcdog
sudo sh -c 'umask 077; printf "%s\\n" "PCDOG_ZEROTIER_NETWORK_ID=<16-znakowy-hex-network-id>" > /etc/pcdog/zerotier.conf'
sudo ./scripts/bootstrap.sh
```

Alternatywnie dla pojedynczego przebiegu: `sudo PCDOG_ZEROTIER_NETWORK_ID=<id> ./scripts/bootstrap.sh`. Nie dodawaj tego pliku ani ID do Gita. Brak Network ID nie blokuje instalacji: bootstrap komunikuje, że join został celowo pominięty.

## Pierwsze dołączenie i autoryzacja

Gdy ID jest skonfigurowane, bootstrap wykonuje `zerotier-cli join` tylko wtedy, gdy urządzenie nie jest jeszcze członkiem wskazanej sieci. `ACCESS_DENIED` oznacza zwykle poprawne dołączenie oczekujące na ręczną autoryzację: zatwierdź node w panelu ZeroTier Central. Bootstrap nie robi automatycznej autoryzacji API ani pętli retry. Błąd polecenia `join` lub nieprawidłowy ID kończy bootstrap błędem.

Kolejne uruchomienie nie reinstaluje ZeroTier, nie wykonuje zbędnego join i nie restartuje aktywnej usługi.

## Diagnostyka i nieużywanie

Pełny, wyłącznie odczytowy raport (wersja, systemd, Node ID, CLI, członkostwo i adresy) daje:

```bash
./scripts/zerotier-status.sh
```

Network ID jest celowo ukryty w raporcie, ponieważ PcDog traktuje go jako konfigurację deploymentu. Można też użyć `systemctl is-enabled zerotier-one`, `systemctl is-active zerotier-one`, `zerotier-cli status` oraz `zerotier-cli listnetworks`.

Aby nie używać ZeroTier, nie twórz `zerotier.conf`; usługa pozostanie dostępna, ale PcDog nie wykona join. Wyłączenie usługi jest świadomą decyzją operatora: `sudo systemctl disable --now zerotier-one`.
