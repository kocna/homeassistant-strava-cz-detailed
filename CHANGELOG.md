# Změny oproti původní integraci

Tento repozitář je upravená kopie integrace
[petr-michal/homeassistant-strava-cz](https://github.com/petr-michal/homeassistant-strava-cz)
(licence GPL-3.0). Níže jsou jen změny proti verzi 0.2.3.

## 0.2.4 – „detailed“

### Přidáno
- **Rozbor jídla po chodech a surovinách** (`detail.py`). U hlavních jídel s alergenem
  03 (vejce), 04 (ryby) nebo 07 (mléko) se načte detail ze Strava.cz
  (`/api/orderModalDetails`). V atributech týdenního jídelníčku přibývají u jídla klíče:
  - `vegan` – `true`, pokud blokující alergen není v hlavním jídle,
  - `rozbor` – věta pro přehled, např. `vegan, ale salát se sýrem (07)`
    nebo `NEVEGAN: Nudle – vejce (03) [Vaječné nudle]`.
  Salát, sýr jako posyp a polévka oběd neblokují, jen se vypíšou.
  Detail se načítá jednou a drží se v paměti, jen na nejbližších 21 dní
  (nejvýše 25 dotazů na jednu aktualizaci). Děti, pro které se detail nemá načítat,
  lze vyjmenovat v `DETAIL_SKIP_NAMES` v `coordinator.py`.
- **Jídelníček příští týden** – nový senzor `Jídelníček příští týden`.
- **Objednávání přesnídávky a svačiny** (jídla typu `unknown`, např. školka) výběrem
  objednávky; dříve se nabízela jen hlavní jídla.

### Změněno
- Interval aktualizace z 1 hodiny na **15 minut**.
- Do dat jídla se ukládá `druh` a číslo jídelníčku (potřebné pro detail).

### Poznámka
Při selhání načtení detailu integrace dál funguje, jen u daného jídla chybí `rozbor`.
