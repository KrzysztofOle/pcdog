# Mapowanie GPIO PcDog

Ten dokument rozdziela zatwierdzone mapowanie logiczne od niepotwierdzonego
jeszcze fizycznego okablowania. Nie jest instrukcją requestowania, odczytu ani
ustawiania GPIO.

## CURRENT BOARD — 4 SIGNALS

Aktualna płytka PcDog jest w trakcie lutowania. Poniższe numery BCM są decyzją
Human Authority. Numery fizycznych pinów 40-pinowego headera zweryfikowano z
[dokumentacją GPIO Raspberry Pi](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio-and-the-40-pin-header).

| Signal | Direction względem Raspberry Pi | BCM GPIO | Physical pin | Rola elektryczna | Physical wiring confirmed |
| --- | --- | --- | --- | --- | --- |
| POWER control | OUTPUT | GPIO16 | 36 | GPIO output → transoptor → F_PANEL POWER switch | NOT TESTED |
| RESET control | OUTPUT | GPIO17 | 11 | GPIO output → transoptor → F_PANEL RESET switch | NOT TESTED |
| HDD LED monitor | INPUT | GPIO19 | 35 | transoptor → GPIO input | NOT TESTED |
| POWER LED monitor | INPUT | GPIO20 | 38 | transoptor → GPIO input | NOT TESTED |

Zatwierdzone mapowanie nie jest fizycznym potwierdzeniem ciągłości ścieżki,
polaryzacji transoptora, poziomów napięć ani bezpieczeństwa elektrycznego.
Każdy z tych faktów wymaga osobnego pomiaru na rzeczywistej płytce.

### Stan statyczny PcDog1

W inspekcji `gpioinfo` dla `pinctrl-bcm2835` (54 linie) GPIO16, GPIO17,
GPIO19 i GPIO20 nie miały consumera i występowały jako input. Nie znaleziono
odwołań do nich w konfiguracji PcDog ani aktywnego SPI1. Każda z tych linii ma
jednak alternatywną funkcję SPI1: odpowiednio CE2, CE1, MISO i MOSI. Przyszłe
włączenie SPI1 albo odpowiedniego overlayu wymaga ponownej oceny konfliktu.

Brak consumera jest tylko obserwacją aktualnego systemu, nie dowodem
bezpieczeństwa elektrycznego ani rezerwacją linii. Linie są kandydatami do
przyszłego użycia PcDog, pod warunkiem osobnego etapu uprawnień, pomiaru i
kontrolowanego testu wejścia.

## FUTURE BOARD — 6 SIGNALS

Przyszła wersja płytki doda dwa wejścia:

- physical POWER button monitor;
- physical RESET button monitor.

Nie przypisano im jeszcze żadnych GPIO ani fizycznych pinów.

## Implementacja i granice sterowania

IMPLEMENTED (software): hardware-agent przekazuje surowe i wiarygodne odczyty
GPIO19/GPIO20 przez `GPIO InputSource -> InputMonitor -> StateEngine`. Debounce
POWER LED i hold HDD pozostają w `InputMonitor`.

Agent zna wyłącznie dwa semantyczne impulsy: `pulse_power` dla GPIO16 i
`pulse_reset` dla GPIO17. Nie przyjmuje numeru linii ani ogólnej operacji
`set_gpio`. Impuls ma domyślnie 200 ms, a ewentualny parametr jest ograniczony
fail-closed do 50–500 ms. Jeden globalny lock odrzuca próbę jednoczesnej
aktywacji. `gpioset --toggle <czas>,0` przełącza wybraną linię z aktywnej na
nieaktywną przed zwolnieniem jej do INPUT; timeout i wyjątek kończą proces
utrzymujący linię.

**FAIL-CLOSED POLARITY:** w zwykłej instalacji GPIO16 i GPIO17 pozostają INPUT,
a `pulse_power`/`pulse_reset` zwracają `ACTION_NOT_ENABLED`. Nie ma domyślnej
polaryzacji. Dopiero udokumentowane, fizyczne potwierdzenie poziomu aktywnego
obu transoptorów może utworzyć plik root-only
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
konfiguracja jest decyzją sprzętową, nie może pochodzić od klienta IPC. Bez
takiego potwierdzenia nie wolno wykonywać live pulse.

`python3 -m pcdog_runtime.hardware_loopback --channel power` lub `--channel
reset` jest narzędziem jednorazowej obserwacji: przez socket wysyła dokładnie
jeden odpowiedni semantyczny impuls i odczytuje GPIO19/GPIO20 podczas jego
trwania. Nie ma argumentu GPIO ani czasu i nie ma bezpośredniego dostępu do
`/dev/gpiochip0`.

### Diagnostyka serwisowa transoptorów

Wyłącznie do kontrolowanej diagnostyki fizycznej, poza Web API i socketem
hardware-agenta, root może uruchomić `/opt/pcdog/bin/pcdog-diagnostic-controls
on`. Narzędzie ma dokładnie dwa polecenia: `on` (`diagnostic_controls_on`) i
`off` (`diagnostic_controls_off`); nie przyjmuje GPIO, czasu ani polaryzacji.
`on` utrzymuje jednocześnie tylko GPIO16 i GPIO17 w stanie ACTIVE/HIGH przez
procesy `gpioset`, bez automatycznego timeoutu. `off` kończy oba procesy i
zwalnia linie. Jest to tryb serwisowy dla stanowiska, na którym PC nie jest
podłączony do linii POWER/RESET; nie zastępuje ani nie rozszerza
`pulse_power`/`pulse_reset`.

LIVE TESTED: brak. Physical wiring GPIO19/GPIO20: **NOT TESTED**. Polaryzacja
GPIO16/GPIO17: **UNCONFIRMED**. POWER i RESET są operacjami podwyższonego
ryzyka; to mapowanie nie upoważnia do ich wykonania.
