# Kontrolowany test płytki GPIO — 2026-09-13

## Zakres i bezpieczeństwo

Test potwierdził zachowanie aktualnej płytki PcDog w kontrolowanym obwodzie
testowym 3.3 V. Wyjścia POWER SW i RESET SW **nie były podłączone do płyty
głównej PC**. Test nie potwierdza zatem jeszcze działania z rzeczywistą płytą
główną PC ani nie upoważnia do jej sterowania.

Testowano osobno każdy kanał; POWER i RESET nie były aktywne jednocześnie. Po
każdym teście wykonano odpowiednie diagnostyczne `*-off`, które wymusza
fizyczne LOW przed zwolnieniem ownership GPIO.

## Potwierdzone mapowanie

| Sygnał | BCM GPIO | Physical pin | Stan aktywny / semantyka |
| --- | --- | --- | --- |
| POWER CONTROL | GPIO17 | 11 | HIGH = ACTIVE, LOW = INACTIVE |
| RESET CONTROL | GPIO18 | 12 | HIGH = ACTIVE, LOW = INACTIVE |
| POWER LED MONITOR | GPIO19 | 35 | open-collector, LOW = active, HIGH = inactive |
| HDD LED MONITOR | GPIO20 | 38 | open-collector, LOW = active, HIGH = inactive |

GPIO16 nie należy do aktualnego mapowania PcDog.

`pcdog-gpio-input-init.service` skonfigurował GPIO19 i GPIO20 jako `input
pull-up` przed startem `pcdog-hardware-agent.service`. Oba wejścia zachowują
semantykę active-low; w spoczynku przy otwartych tranzystorach monitorujących
były fizycznie HIGH.

## Topologia testowa

Obwód testowy miał osobne zasilanie 3.3 V i rezystor 1 kΩ.

- POWER loop: GPIO17 → T1 → obwód testowy → T3 → GPIO19.
- RESET loop: GPIO18 → T2 → obwód testowy → T4 → GPIO20.

## Wyniki

### POWER loop — PASS

- Baseline: GPIO17 LOW/INACTIVE, GPIO19 HIGH, GPIO20 HIGH.
- `power-on`: GPIO17 HIGH/ACTIVE, GPIO19 LOW.
- GPIO20 pozostało HIGH: **brak cross-talk**.
- `power-off`: GPIO17 LOW/INACTIVE, GPIO19 HIGH.

### RESET loop — PASS

- Baseline: GPIO18 LOW/INACTIVE, GPIO20 HIGH, GPIO19 HIGH.
- `reset-on`: GPIO18 HIGH/ACTIVE, GPIO20 LOW.
- GPIO19 pozostało HIGH: **brak cross-talk**.
- `reset-off`: GPIO18 LOW/INACTIVE, GPIO20 HIGH.

### OFF behavior — PASS

Diagnostyczne `power-off` i `reset-off` wymusiły fizyczne LOW na właściwym
wyjściu przed zwolnieniem `gpioset`; samo zwolnienie linii nie jest traktowane
jako gwarancja LOW.

## Końcowy bezpieczny stan

- GPIO17 LOW / INACTIVE;
- GPIO18 LOW / INACTIVE;
- GPIO19 HIGH / monitor nieaktywny;
- GPIO20 HIGH / monitor nieaktywny;
- brak procesu `gpioset`;
- diagnostic lock unlocked;
- `pcdog-gpio-input-init.service` active/exited, success;
- `pcdog-hardware-agent.service` active/running, `NRestarts=0`;
- healthcheck `HEALTHY`;
- bez rebootu.

## Następny etap

Następne działania muszą zachować kolejność **observation → simulation →
controlled test → real control**:

1. odczytowy test rzeczywistych POWER LED i HDD LED na PC, bez sterowania
   POWER/RESET;
2. osobny kontrolowany test POWER CONTROL z podłączoną płytą główną;
3. RESET CONTROL dopiero po powodzeniu testu POWER CONTROL.
