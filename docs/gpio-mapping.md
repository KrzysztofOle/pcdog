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

## Granice przyszłej implementacji

Adapter GPIO będzie przekazywał wyłącznie surowe i wiarygodne odczyty przez
`GPIO InputSource -> InputMonitor -> StateEngine`. Debounce POWER LED i hold
HDD pozostają w `InputMonitor`. POWER i RESET są operacjami podwyższonego
ryzyka i wymagają osobnego zatwierdzenia Human Authority; to mapowanie nie
upoważnia do ich wykonania.
