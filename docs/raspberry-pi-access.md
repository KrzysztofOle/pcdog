# Dostęp do Raspberry Pi PcDog1

## Dane urządzenia

- hostname: `PcDog1`
- obecnie używany adres IP: `192.168.7.162`
- użytkownik SSH: `krzysztof`
- system potwierdzony zdalnie: Debian / Raspberry Pi OS, `aarch64`

Adres IP może się zmienić, dlatego przed użyciem należy w razie potrzeby potwierdzić go w sieci lokalnej.

## Połączenie SSH

Standardowe polecenie:

```bash
ssh krzysztof@192.168.7.162
```

Uwierzytelnianie korzysta z istniejącego klucza SSH dostępnego na komputerze developerskim. Klucza prywatnego, haseł ani zawartości `~/.ssh` nie przechowujemy w repozytorium.

Prosty test dostępności:

```bash
ssh -o BatchMode=yes krzysztof@192.168.7.162 'hostname'
```

## Diagnostyka

Jeśli połączenie przestanie działać:

1. Sprawdź, czy Raspberry Pi jest uruchomione i podłączone do właściwej sieci.
2. Sprawdź, czy adres IP nadal jest aktualny, np. w konfiguracji routera lub na urządzeniu.
3. Sprawdź odpowiedź urządzenia w sieci:

   ```bash
   ping -c 3 192.168.7.162
   ```

4. Sprawdź dostępność portu SSH:

   ```bash
   nc -vz 192.168.7.162 22
   ```

5. Sprawdź, czy właściwy klucz SSH jest dostępny lokalnie i czy klient SSH go używa. Nie umieszczaj klucza prywatnego ani jego treści w repozytorium.
6. Sprawdź wpis host key bez wyłączania weryfikacji hosta:

   ```bash
   ssh-keygen -F 192.168.7.162
   ```

   Jeśli SSH zgłasza zmianę host key, potwierdź tożsamość urządzenia i aktualizuj lokalny `known_hosts` dopiero po tej weryfikacji. Nie używaj `StrictHostKeyChecking=no`.

7. Uruchom test z większą ilością informacji, nie ujawniając sekretów:

   ```bash
   ssh -vv -o BatchMode=yes krzysztof@192.168.7.162 'hostname'
   ```

