# Mapowanie GPIO PcDog

Ten dokument opisuje zatwierdzone mapowanie i aktualny stan weryfikacji płytki.
Nie jest instrukcją samodzielnego requestowania, odczytu ani ustawiania GPIO.

## CURRENT BOARD — 4 SIGNALS

Poniższe numery BCM są źródłem prawdy dla aktualnej płytki PcDog. Numery
fizycznych pinów 40-pinowego headera zweryfikowano z [dokumentacją GPIO
Raspberry Pi](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio-and-the-40-pin-header).

| Signal | Direction względem Raspberry Pi | BCM GPIO | Physical pin | Rola elektryczna | Physical wiring confirmed |
| --- | --- | --- | --- | --- | --- |
| POWER control | OUTPUT | GPIO17 | 11 | GPIO → 680 Ω → LED transoptora T1 → GND | ACTIVE-HIGH; controlled loop PASS |
| RESET control | OUTPUT | GPIO18 | 12 | GPIO → 680 Ω → LED transoptora T2 → GND | ACTIVE-HIGH; controlled loop PASS |
| POWER LED monitor | INPUT | GPIO19 | 35 | open-collector transoptora T3 → GPIO input | active-low pull-up; controlled loop PASS |
| HDD LED monitor | INPUT | GPIO20 | 38 | open-collector transoptora T4 → GPIO input | active-low pull-up; controlled loop PASS |

GPIO19 i GPIO20 są wejściami transoptorów open-collector aktywnymi stanem
LOW. `pcdog-gpio-input-init.service` trwałe ustawia dla nich `input pull-up`
przed startem agenta, a każdy odczyt `gpioget` żąda `pull-up` oraz
`--active-low`. Stan wysoki jest więc elektrycznie nieaktywny, a niski oznacza
aktywny POWER LED lub HDD.

GPIO16 nie jest częścią aktualnego mapowania PcDog i nie jest kanałem POWER,
RESET ani monitora.

Kontrolowany test płytki z 2026-09-13 potwierdził oba tory, aktywność LOW
monitorów, brak cross-talk oraz wymuszanie bezpiecznego LOW przez diagnostyczne
OFF. Pełny, trwały zapis znajduje się w [raporcie testu płytki](gpio-controlled-board-test-2026-09-13.md).
Test nie obejmował rzeczywistej płyty głównej PC: PC nie był podłączony do
POWER ani RESET.

### Historyczna inspekcja statyczna PcDog1

Poniższa obserwacja pochodzi z etapu przed wdrożeniem runtime i przed
kontrolowanym testem płytki; zachowano ją jako kontekst historyczny, nie opis
obecnego stanu. W inspekcji `gpioinfo` dla `pinctrl-bcm2835` (54 linie) GPIO17, GPIO18,
GPIO19 i GPIO20 nie miały consumera i występowały jako input. Nie znaleziono
odwołań do nich w konfiguracji PcDog ani aktywnego SPI1. Każda z tych linii ma
jednak alternatywną funkcję SPI1: odpowiednio CE1, CE0, MISO i MOSI. Przyszłe
włączenie SPI1 albo odpowiedniego overlayu wymaga ponownej oceny konfliktu.

Brak consumera był tylko obserwacją tamtego systemu, nie dowodem bezpieczeństwa
elektrycznego ani rezerwacją linii.

## FUTURE BOARD — 6 SIGNALS

Przyszła wersja płytki doda dwa wejścia:

- physical POWER button monitor;
- physical RESET button monitor.

Nie przypisano im jeszcze żadnych GPIO ani fizycznych pinów.

## Implementacja i granice sterowania

IMPLEMENTED (software): hardware-agent przekazuje surowe i wiarygodne odczyty
GPIO19 (POWER LED) i GPIO20 (HDD LED) przez
`GPIO InputSource -> InputMonitor -> StateEngine`. Debounce POWER LED i hold
HDD pozostają w `InputMonitor`.

Agent zna wyłącznie dwa semantyczne impulsy: `pulse_power` dla GPIO17 i
`pulse_reset` dla GPIO18. Nie przyjmuje numeru linii ani ogólnej operacji
`set_gpio`. Impuls ma domyślnie 200 ms, a ewentualny parametr jest ograniczony
fail-closed do 50–500 ms. Jeden globalny lock odrzuca próbę jednoczesnej
aktywacji. `gpioset --toggle <czas>,0` przełącza wybraną linię z aktywnej na
nieaktywną przed zwolnieniem jej do INPUT; timeout i wyjątek kończą proces
utrzymujący linię.

**FAIL-CLOSED POLARITY:** w zwykłej instalacji GPIO17 i GPIO18 pozostają INPUT,
a `pulse_power`/`pulse_reset` zwracają `ACTION_NOT_ENABLED`. Nie ma domyślnej
polaryzacji. Kontrolowany test płytki potwierdził dla jej dwóch wyjść
ACTIVE-HIGH, ale runtime wymaga nadal jawnej lokalnej konfiguracji root-only
`/etc/pcdog/hardware-control.conf` o dokładnej treści jednej z poniższych:

```text
PCDOG_CONTROL_POLARITY=active-high
```

lub:

```text
PCDOG_CONTROL_POLARITY=active-low
```

Następnie wymagany jest kontrolowany restart tylko
`pcdog-hardware-agent.service` i ponowne sprawdzenie baseline wejść. Ta
konfiguracja jest decyzją sprzętową, nie może pochodzić od klienta IPC.
Potwierdzenie na obwodzie testowym nie zastępuje oddzielnej decyzji Human
Authority o sterowaniu rzeczywistym PC.

`python3 -m pcdog_runtime.hardware_loopback --channel power` lub `--channel
reset` jest narzędziem jednorazowej obserwacji: przez socket wysyła dokładnie
jeden odpowiedni semantyczny impuls i odczytuje GPIO19/GPIO20 podczas jego
trwania. Nie ma argumentu GPIO ani czasu i nie ma bezpośredniego dostępu do
`/dev/gpiochip0`.

### Diagnostyka serwisowa GPIO

Wyłącznie do kontrolowanej diagnostyki fizycznej, poza Web API i socketem
hardware-agenta, root uruchamia `pcdog-test` (instalowane także jako
`/opt/pcdog/bin/pcdog-test`). Przyjmuje tylko
`status`, `inputs`, `outputs`, `power-on`, `power-off`, `reset-on`,
`reset-off`, `all-on` i `all-off`; nie przyjmuje GPIO, czasu ani polaryzacji.
GPIO17 i GPIO18 są zawsze ACTIVE-HIGH. Polecenia `*-on` utrzymują stan aż do
odpowiedniego `*-off`. Każde `*-off` najpierw wykonuje `pinctrl set <GPIO> op
dl`, wymuszając fizyczne LOW/INACTIVE, a dopiero potem kończy proces `gpioset`
i zwalnia linię; `all-off` najpierw ustawia LOW na obu wyjściach, następnie
zwalnia oba procesy. Niepowodzenie ustawienia LOW zachowuje ownership, zamiast
zwolnić linię o nieznanym poziomie. `status` używa odczytowo `gpioinfo` do
potwierdzenia kierunku i `pinctrl get <GPIO>` do potwierdzenia fizycznego
poziomu; rozbieżność albo brak któregoś odczytu jest raportowana jako
`UNKNOWN`.

Własność GPIO17/18 jest synchronizowana wspólną blokadą
`/run/pcdog-gpio-control.lock`: proces `gpioset` diagnostyki dziedziczy ją na
czas utrzymywania wyjścia, a hardware-agent trzyma ją przez ograniczony
impuls. Dzięki temu agent odrzuca konflikt jako `OUTPUT_BUSY`, zamiast dwóch
procesów próbujących przejąć tę samą linię. Poprzednie root-only
`pcdog-diagnostic-controls on|off` pozostaje zgodnym aliasem odpowiednio dla
`pcdog-test all-on|all-off`; nie stanowi drugiego modelu własności.

Human Authority potwierdził fizyczną tożsamość wszystkich czterech torów:
GPIO17 → POWER SW, GPIO18 → RESET SW, GPIO19 ← POWER LED, GPIO20 ← HDD LED.
Nie zastępuje to kontrolowanego testu działania PC. POWER i RESET są
operacjami podwyższonego ryzyka; to mapowanie nie upoważnia do ich wykonania.

## Status testów i następny etap

**COMPLETE / PASS:** kontrolowany test płytki GPIO z 2026-09-13, opisany w
[raporcie](gpio-controlled-board-test-2026-09-13.md), potwierdził POWER loop
GPIO17→GPIO19 oraz RESET loop GPIO18→GPIO20, bez cross-talk i z bezpiecznym
OFF. Końcowy stan to GPIO17/18 LOW oraz GPIO19/20 HIGH.

Kolejny etap ma zachować kolejność **observation → simulation → controlled
test → real control**:

1. obserwacyjny test rzeczywistych POWER LED i HDD LED na PC, bez sterowania
   POWER/RESET;
2. osobny, kontrolowany test POWER CONTROL z rzeczywistą płytą główną;
3. RESET CONTROL dopiero po powodzeniu poprzedniego etapu.
