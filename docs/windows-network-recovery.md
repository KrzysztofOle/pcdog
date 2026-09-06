# Ręczna diagnostyka i recovery sieci Windows

`windows-network-recovery.py` jest ręcznym narzędziem V1 uruchamianym na PcDog1. Łączy się wyłącznie z Windows przez kanał serwisowy USB `172.23.254.1/30` → `172.23.254.2`, a nie przez kartę internetową Windows. Nie jest watchdogiem i samo wykonanie diagnostyki nie zmienia Windows.

## Uruchomienie

Podaj jawnie konto Windows oraz adapter przeznaczony do Internetu. Alias jest celowy: operator musi wskazać adapter, który wolno potencjalnie zrestartować.

```bash
./scripts/windows-network-recovery.py --ssh-user <konto-admin-Windows> --adapter 'Wi-Fi'
```

Polecenie zwraca jednolinijkowy JSON ze `status` i snapshotem diagnostycznym. Używa systemowego klienta SSH; może więc poprosić operatora o hasło, ale go nie zapisuje. Zalecanym kolejnym krokiem operacyjnym jest skonfigurowanie oddzielnego klucza SSH dla konta administracyjnego Windows, poza tym repozytorium.

Recovery Level 1 wymaga dodatkowej, jawnej flagi:

```bash
./scripts/windows-network-recovery.py --ssh-user <konto-admin-Windows> --adapter 'Wi-Fi' --recover
```

Konfigurowalne czasy domyślne to: pierwsze oczekiwanie 10 s, retry co 5 s i maksymalne okno 60 s. Można je zmienić przez `--initial-delay`, `--retry-interval` oraz `--timeout`. Wszystkie wartości są walidowane.

## Diagnostyka i statusy

Kolejność klasyfikacji to `HEALTHY` (0), `SSH_UNAVAILABLE` (10), `ADAPTER_DOWN` (11), `NO_IPV4` (12), `NO_GATEWAY` (13), `GATEWAY_UNREACHABLE` (14), `INTERNET_UNREACHABLE` (15) i `DNS_FAILURE` (16). Sprawdzane są: SSH, stan adaptera, IPv4, trasa domyślna na tym adapterze, brama, Internet po IP (domyślnie `1.1.1.1`) i DNS (domyślnie `one.one.one.one`).

Po `--recover` możliwe są także `RECOVERED` (0), `RECOVERY_TIMEOUT` (30), `RECOVERY_FAILED` (31) i `SERVICE_INTERFACE_PROTECTED` (32). Błędy argumentów mają kod 64.

## Ochrona kanału serwisowego

Recovery nie ufa aliasowi `Ethernet 2`. Na Windows zdalny skrypt enumeruje adaptery i uznaje kanał PcDog za jednoznacznie rozpoznany tylko wtedy, gdy dokładnie jeden adapter ma jednocześnie adres `172.23.254.2/30` i dokładny opis `Remote NDIS Compatible Device`. Każdy częściowy, wielokrotny lub brakujący sygnał jest niejednoznaczny i blokuje recovery fail-safe. Recovery jest także blokowane, gdy wskazany adapter jest wykrytym adapterem serwisowym.

Ta kontrola występuje dwa razy: przed operacją po stronie PcDog oraz wewnątrz zdalnego PowerShell bezpośrednio przed `Restart-NetAdapter`. Narzędzie nie wykonuje `netsh`, zmian tras, firewalla, USB, ZeroTier, GPIO, POWER, RESET ani restartu Windows.

## Recovery Level 1

Po pomyślnej walidacji jedyną operacją modyfikującą jest:

```powershell
Restart-NetAdapter -Name <jawnie-wskazany-adapter> -Confirm:$false
```

Następnie narzędzie czeka czas stabilizacji i powtarza pełną diagnostykę aż do `HEALTHY` albo końca okna. Nie należy oceniać wyniku tuż po restarcie adaptera.

## Pierwszy kontrolowany live test

To jest procedura dla Human Authority — nie jest wykonywana automatycznie:

1. Z PcDog1 uruchom diagnostykę bez `--recover` dla `--adapter 'Wi-Fi'` i zachowaj JSON.
2. Potwierdź w snapshotcie, że USB ma adres `172.23.254.2/30` i opis `Remote NDIS Compatible Device`, a wybrany adapter jest inny.
3. Utrzymaj otwartą osobną sesję SSH PcDog1 → Windows po `172.23.254.2`.
4. Uruchom `--recover` z domyślnym oknem 60 s; obserwuj JSON i tę sesję USB.
5. Wynik `RECOVERED` wymaga `HEALTHY`; przy `RECOVERY_TIMEOUT` lub `SERVICE_INTERFACE_PROTECTED` nie wykonuj dodatkowych resetów — zachowaj wynik do diagnozy.

Przyszły watchdog może użyć tych samych statusów i czystej polityki, ale nie jest implementowany w V1.
