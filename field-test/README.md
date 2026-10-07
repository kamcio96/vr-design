# Test terenowy: instrukcja

Strona testowa sprawdza dwie rzeczy:
- czy na Questach da się chodzić bez granicy bezpieczeństwa,
- o ile przesuwa się obraz względem rzeczywistości (dryf) podczas spaceru.

Wyniki zapisują się same na laptopie.

## Co zabrać

- 2× Quest 3S (naładowane), laptop, router Wi-Fi z powerbankiem.
- 2–4 paliki i miarkę.
- **Zaślepki na soczewki.** Słońce padające na soczewki uszkadza ekrany w mniej niż minutę.

## Przygotowanie (raz, w domu)

1. Na laptopie otwórz terminal w folderze projektu i wpisz:
   ```
   cd field-test
   npm install
   ```

## Na miejscu

1. Połącz laptop i gogle z tym samym Wi-Fi (twój router).
2. Na laptopie, w folderze `field-test`, uruchom:
   ```
   npm run dev
   ```
   W terminalu pojawi się adres w rodzaju `https://192.168.x.x:5174`. Nie zamykaj terminala.
3. W goglach otwórz przeglądarkę i wpisz ten adres.
4. Przeglądarka ostrzeże, że połączenie nie jest prywatne. To normalne, bo certyfikat jest nasz własny. Wybierz **Zaawansowane → Przejdź do strony**. Wystarczy raz.
5. Wybierz **Start MR** albo **Start VR** i zaakceptuj prośby o dostęp.

## Sterowanie (prawy kontroler)

| Przycisk | Działanie |
|---|---|
| Spust | postaw znacznik w miejscu kontrolera |
| Grip (boczny) | pomiar: odchyłka od najbliższego znacznika |
| A | przezroczystość siatki i znaczników |
| B | wyślij wyniki teraz (wysyłają się też same) |

Nad lewym kontrolerem widać tablicę z informacjami:
- **Przestrzeń**: `unbounded` oznacza, że chodzenie bez granicy działa. `local-floor` oznacza, że granica jest aktywna.
- odległość od punktu startu,
- przebyty dystans,
- liczba klatek na sekundę (FPS),
- wynik ostatniego pomiaru.

## Przebieg testu

1. **Start w środku przyszłego domu.** Wbij palik nr 1 obok siebie i uruchom sesję MR.
2. Przyłóż prawy kontroler do czubka palika i naciśnij **spust**. Pojawi się znacznik nr 1.
3. Przejdź 15–20 m: po obwodzie domu, w najdalszy narożnik.
4. Wróć do palika, przyłóż kontroler **tak samo jak wcześniej** i naciśnij **grip**. Tablica pokaże odchyłkę w cm.
5. Powtórz 2–3 razy, za każdym razem dłuższą trasą.
6. Sprawdź, co się dzieje, gdy odejdziesz ponad 20 m od startu (spodziewany komunikat gogli).
7. To samo zrób w trybie **VR**. Zanotuj, kiedy pojawia się granica bezpieczeństwa.
8. Najlepiej powtórzyć test na trawie i w pustym pomieszczeniu, w pochmurny i słoneczny dzień, oraz o zmierzchu.
9. Drugie gogle: ten sam test równolegle. Każde gogle zapisują osobny plik.

## Wyniki

Pliki JSON pojawiają się na laptopie w `field-test/results/`. W nazwie pliku jest data, tryb (MR/VR) i typ przestrzeni. Najważniejsze pola:
- `referenceSpace`: czy udało się `unbounded`,
- `refSpaceErrors`: dlaczego inne typy przestrzeni się nie udały,
- `measurements`: odchyłki (`horizontalCm`) i dystans od postawienia znacznika (`pathSinceMarkerM`),
- `maxDistanceM`: najdalsze miejsce od startu,
- `track`: ślad trasy co sekundę.

Wyniki przekaż Claude, który podsumuje je w `AGENTS.md` i zaproponuje wybór technologii.
