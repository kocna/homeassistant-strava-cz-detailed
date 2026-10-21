# Strava.cz pro Home Assistant

Custom integrace pro Home Assistant, která zpřístupňuje data ze školních jídelen
používajících Strava.cz.

Integrace vychází z knihovny:
https://github.com/jsem-nerad/strava-cz-python

> **Osobní fork.** Tato kopie je upravená pro vlastní potřebu rodiny a je veřejná jen proto,
> že HACS neumí instalovat ze soukromých repozitářů. Není určená k doporučování ani
> k obecnému použití, nenabízí podporu a nemusí se aktualizovat. Používáš ji na vlastní
> riziko (viz GPL-3.0, bez záruky). Chceš-li stabilní integraci, použij originál od
> @petr-michal: https://github.com/petr-michal/homeassistant-strava-cz

## Tato verze (0.2.4, „detailed“)

Upravená kopie integrace od @petr-michal (licence GPL-3.0). Přidává:

- **Rozbor jídla po chodech a surovinách.** U hlavních jídel s alergenem 03 (vejce),
  04 (ryby) nebo 07 (mléko) načte detail ze Strava.cz (`orderModalDetails`) a v atributech
  týdenního jídelníčku přidá `vegan` a `rozbor` (např. „vegan, ale salát se sýrem (07)“).
  Salát, sýr jako posyp a polévka oběd neblokují, jen se vypíšou. Detail se načítá jednou
  a drží se v paměti, jen pro vybrané děti a na nejbližší tři týdny.
- **Jídelníček příští týden** (nový senzor `Jídelníček příští týden`).
- **Objednávání přesnídávky a svačiny** (jídla typu `unknown`, např. školka) přes stejný výběr.
- **Kratší interval aktualizace**: 15 minut místo hodiny.

Instalace přes HACS: HACS → ⋮ → Vlastní repozitáře → adresa tohoto repozitáře, kategorie
Integrace. Původní integraci Strava.cz v HACS nejdřív odstraň (nastavení účtů zůstane).

Původní popis integrace:

## Verze 0.2.3

Verze 0.2.3 přidává srozumitelnou výchozí volbu do ovládacích prvků pro objednání a zrušení oběda. Verze 0.2.2 přidala týdenní jídelníček pro celý pracovní týden. Zachovává také opravené popisky výběru přihlášení a číslo jídelny u zařízení.\n\nIntegrace podporuje dva způsoby přihlášení:

### Osobní účet – doporučeno

Přihlášení e-mailem a heslem osobního účtu Strava.cz.

Integrace automaticky načte všechny propojené účty jídelen a každý vytvoří jako
samostatné zařízení v Home Assistantu.

To znamená například:

- Anna – jídelna 0031
- Kryštof – jídelna 0031
- Adéla – jídelna 0176

Stačí jedno přihlášení osobním účtem.

Použitý tok Strava.cz API:

- `loginPA`
- `jidelnyPA`
- `canteenLoginPA`
- `s4Polozky`
- `nactiVlastnostiPA`
- `objednavky`

### Účet jídelny

Původní přihlášení pomocí:

- uživatelského jména
- hesla
- čísla jídelny

zůstává zachováno kvůli zpětné kompatibilitě.

## Entity pro každý účet jídelny

- Zůstatek
- Dnešní oběd
- Zítřejší oběd
- Příští objednaný oběd
- Objednat oběd
- Zrušit oběd\n- Týdenní jídelníček (pondělí–pátek, všechny varianty a stav objednávky)

## Důležitá poznámka

Strava.cz používá pro český jazyk v API hodnotu `CZ`. Hodnota `CS` způsobovala
timeout přihlášení a v této integraci se nepoužívá.

## Instalace

Složku:

`custom_components/strava_cz`

zkopíruj do:

`/config/custom_components/strava_cz`

a restartuj Home Assistant.

Pro HACS (vlastní repozitář, kategorie Integrace) použij tento repozitář:

https://github.com/kocna/homeassistant-strava-cz-detailed

Původní (neupravená) integrace je zde: https://github.com/petr-michal/homeassistant-strava-cz

## Licence

GNU GPL v3.0. Integrace používá `strava-cz==0.4.0`.


## Logo

Integrace používá oficiální logomark Strava.cz z:
https://app.strava.cz/logo/logomark.svg

Od Home Assistantu 2026.3 jsou brand obrázky custom integrací načítány přímo
z adresáře `custom_components/strava_cz/brand/`.
