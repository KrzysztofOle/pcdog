# Rekomendowany system Raspberry Pi dla PcDog

## Wybór systemu

Oficjalnie rekomendowanym systemem PcDog jest aktualne, niearchiwalne wydanie
**Raspberry Pi OS Lite (64-bit)**, instalowane przez Raspberry Pi Imager.
Należy wybrać obraz Lite, nie wariant Desktop, Full ani Legacy.

Raspberry Pi OS jest oficjalnym systemem dla Raspberry Pi, a Zero 2 W jest
wspierany przez wydanie 64-bitowe. Płytka ma 64-bitowy procesor ARM Cortex-A53,
więc obraz 64-bitowy odpowiada jej architekturze i pozwala używać współczesnych
pakietów arm64. Wersja Lite jest przeznaczona dla systemu bez monitora i
środowiska graficznego: oszczędza miejsce na karcie, pamięć RAM i czas
aktualizacji, a PcDog będzie zarządzany przez SSH.

Źródła producenta: [Raspberry Pi OS](https://www.raspberrypi.com/documentation/computers/os.html),
[lista zgodnych modeli](https://www.raspberrypi.com/software/operating-systems/) oraz
[specyfikacja Zero 2 W](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/).

## Przygotowanie nośnika w Raspberry Pi Imager

1. Wybierz urządzenie **Raspberry Pi Zero 2 W**.
2. Wybierz **Raspberry Pi OS (other)**, a następnie **Raspberry Pi OS Lite (64-bit)**.
   Wybieraj bieżące wydanie, nie `Legacy`.
3. Wybierz właściwą kartę microSD. Zapis obrazu kasuje jej poprzednią zawartość.
4. Otwórz dostosowanie systemu (Imager proponuje je przed zapisem) i ustaw:

   - **Hostname**: unikalną, małoliterową nazwę, np. `pcdog1` albo `pcdog-gabinet`.
     Nie wpisuj stałego adresu IP; jest przydzielany przez sieć i może się zmienić.
   - **Localisation**: właściwą strefę czasową, układ klawiatury i kraj Wi-Fi.
   - **User**: osobnego administratora o nazwie złożonej z małych liter, cyfr,
     `_` lub `-`; ustaw silne, unikalne hasło do `sudo`.
   - **Wi-Fi**: SSID i hasło właściwej sieci oraz poprawny kraj. Przy ukrytej
     sieci włącz opcję `Hidden SSID`.
   - **Remote Access**: włącz SSH i wybierz **public key authentication**.
     Wklej wyłącznie klucz publiczny, zwykle zawartość pliku `~/.ssh/id_ed25519.pub`.
     Nie wklejaj klucza prywatnego ani nie umieszczaj go w repozytorium.

5. Zapisz i zweryfikuj nośnik w Imager, włóż go do Raspberry Pi, a następnie
   podłącz zasilanie. Po pierwszym uruchomieniu połącz się przez
   `ssh <użytkownik>@<hostname>.local` lub przez aktualny adres z DHCP.

Raspberry Pi Imager umożliwia przed pierwszym startem ustawienie hostname,
użytkownika, Wi-Fi, SSH i klucza publicznego. Oficjalna instrukcja dla zestawu
headless zaleca Raspberry Pi OS Lite i skonfigurowanie zdalnego dostępu w Imager:
[Getting started](https://www.raspberrypi.com/documentation/computers/getting-started.html).

## Bootstrap PcDog

Po zalogowaniu:

```bash
git clone <adres-repozytorium-pcdog>
cd pcdog
./scripts/bootstrap.sh --check
sudo ./scripts/bootstrap.sh
```

`./scripts/bootstrap.sh --check` jest wyłącznie odczytowy i służy do kontroli
przed instalacją: sprawdza Raspberry Pi OS, architekturę arm64 i model Zero 2 W.
Po pełnej instalacji można dodatkowo uruchomić
`./scripts/verify-installation.sh --check`, aby sprawdzić pakiety i katalogi
PcDog. Zwykły bootstrap najpierw wykonuje ten sam preflight, później instaluje
mały zestaw zależności i tworzy katalogi przygotowane dla kolejnych komponentów.
Każdy etap jest bezpieczny do powtórzenia.

W pierwszej fazie bootstrap celowo nie konfiguruje GPIO, usługi systemd,
watchdoga, aplikacji PcDog, logowania aplikacyjnego, aktualizacji ani ustawień
sieci. Te funkcje zostaną dodane jako osobne etapy po ustaleniu ich wymagań.
