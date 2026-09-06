# Bootstrap SSH PcDog → Windows przez USB

`bootstrap-windows-ssh.py` tworzy (lub weryfikuje) lokalny, dedykowany klucz
`~/.ssh/pcdog_windows_ed25519`, a następnie instaluje jego część publiczną przez
jeden interaktywny login SSH. Hasło obsługuje wyłącznie standardowy klient `ssh`:
nie jest argumentem, zmienną środowiskową, plikiem ani elementem logu.

Skrypt najpierw sprawdza TCP/22 oraz istniejące logowanie kluczem w `BatchMode`.
Jeżeli ono działa, kończy się `PASS` bez pytania o hasło. Przy niekompletnej lub
niedopasowanej parze kluczy zatrzymuje się fail-safe, bez nadpisania plików.

W czasie interaktywnego połączenia Windows uruchamia `sshd.exe -T -C` dla
zalogowanego użytkownika i odczytuje aktywne `AuthorizedKeysFile`. Obsługiwane
są wyłącznie jednoznaczne, standardowe lokalizacje: profil użytkownika
`.ssh/authorized_keys` oraz wynikający z aktywnej konfiguracji
`%ProgramData%\\ssh\\administrators_authorized_keys`. Wpis jest porównywany po
typie i materiale klucza, dlatego ponowny bootstrap go nie duplikuje. ACL pliku
jest ograniczany do właściciela i `SYSTEM` (konto zwykłe) albo `Administrators`
i `SYSTEM` (plik administratorów). `sshd_config` nie jest modyfikowany ani
usługa nie jest restartowana.

Po pomyślnym bootstrapie `windows-network-recovery.py` domyślnie używa tego
samego klucza z `BatchMode=yes`, `IdentitiesOnly=yes` i wyłączonym fallbackiem
do hasła.

## Pierwszy live bootstrap — HUMAN AUTHORITY REQUIRED

Na PcDog1, po potwierdzeniu że kanał USB ma adres `172.23.254.1/30` i Windows
jest dostępny pod `172.23.254.2`, uruchom:

```bash
cd <katalog-repozytorium-pcdog>
./scripts/bootstrap-windows-ssh.py --ssh-user admin
```

Skrypt może najpierw utworzyć lokalny klucz i wykona test bez hasła. Jeśli test
nie powiedzie się, standardowy klient SSH poprosi o potwierdzenie host key lub
hasło Windows. Dopiero wtedy Human Authority wpisuje hasło interaktywnie.
Oczekiwany wynik końcowy to `PASS: key auth configured` lub `PASS: key auth
already works`. Wynik `FAIL` należy zachować wraz z pełnym komunikatem; nie
zmieniaj ręcznie `sshd_config`, ACL, firewalla ani usługi `sshd` w ramach tej
procedury.
