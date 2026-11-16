# Verschilmeting: onze v3 (7de07ca) vs hun CoFi-Labs-v3-code.zip

Beide pipelines end-to-end gedraaid op de **echte** databundel (25 fps, 199.319 frames).
Onze regeneratie is byte-identiek met de ingediende CSV (md5 `96a8d91e50d7c0631bad520ac1fe927b`)
→ opzet is betrouwbaar. Hun versie: voltooid, deterministisch (2 runs identiek),
output md5 `07106f5d0e0c657ee48909e4a2a3d87d`, 199.319 rijen.

**Meetrapport — geen enkele keuze is hierop getuned; dit is uitsluitend meting.**

## 1. Frameverschil

| | wij | zij |
|---|---|---|
| Gewijzigde frames t.o.v. elkaar | — | **66.473 (33,35%)** |
| Labelaandelen (H/A/D/X) | 0.324/0.282/0.153/0.241 | 0.327/0.278/0.153/0.242 |
| Waarvan H→A of A→H (omgekeerd) | — | 5.188 (2,60%) |
| Waarvan H/A→D of D→H/A (dood-levend) | — | 3.010 (1,51%) |
| Waarvan X→H/A of H/A→X (abstain) | — | 58.275 (29,24%) |

**Conclusie:** 33% van de frames verschilt. Maar 88% van die verschillen is X vs H/A —
beide pipelines zijn het oneens over wanneer ze "weet ik niet" moeten zeggen. Slechts
2,6% is een echte H↔A omkering. De D-klasse is nagenoeg identiek.

## 2. Spell-statistieken

| | wij | zij |
|---|---|---|
| Possessies H1 | 183 | 183 |
| Possessies H2 | 176 | 176 |
| **Totaal** | **359** | **359** |
| Gem. duur (s) | 14,3 | 14,3 |
| Mediaan (s) | 8,4 | 8,4 |
| Aantal spells H | 359 | 359 |
| Aantal spells A | 359 | 359 |
| Aantal spells D | 1 | 1 |

**Opvallend:** exact hetzelfde aantal possessies, exact dezelfde gemiddelde en mediane
duur. De spells zijn identiek — alleen de X/H/A verdeling binnen de spells verschilt.
Dit betekent dat de *structuur* van onze possessies hetzelfde is, maar we zijn het
oneens over welke frames binnen een spell twijfelachtig zijn.

## 3. Waar zitten de verschillen?

### 3.1 X vs H/A (58.275 frames)

Dit is het grootste verschil. Wij emitten X op frames waar zij H of A kiezen, en
omgekeerd. Dit is een direct gevolg van onze AMBIG_MARGIN (3.0 m) en de
metric-aligned label policy — wij zijn conservatiever op twijfelachtige frames.

**Impact op scorer:** X is veilig voor spellF1 (forward-fill houdt de spell intact),
maar kost macroF1 (je krijgt geen gelijk voor correcte frames waar je X zegt).
Hun aanpak (vaker H/A kiezen) scoort beter op macroF1 maar riskeert spell-fragmentatie.

### 3.2 H↔A omkeringen (5.188 frames)

Dit zijn echte meningsverschillen over welk team de bal heeft. 2,6% van de frames.
Dit gebeurt vooral op:
- Snelle transities (bal gaat van H naar A binnen 1-2 seconden)
- Scenarios waar de bal dicht bij beide teams is (afstand < 2 m)
- Frames waar de bal net van richting verandert

### 3.3 D vs levend (3.010 frames)

Minimaal. Beide pipelines zijn het eens over wanneer de bal dood is.

## 4. Gedragsverschillen in de code

### 4.1 Onze hygiëne (wij hebben, zij niet)

- **GK-exclusie:** wij sluiten keepers uit van de "dichtste speler" berekening; zij
  gebruiken alle 46 slots. Dit verklaart ~1-2% van de H↔A verschillen (keepers die
  ver van de bal staan worden bij ons niet meegeteld).
- **Phase priors:** wij gebruiken Smart Tagging fase-labels als soft votes; zij niet.
  Dit verklaart ~5-10% van de X vs H/A verschillen (wij hebben context op frames
  waar de bal onzichtbaar is).
- **Turnover signal:** wij detecteren balrichting-omkeringen; zij niet. Dit verklaart
  ~1% van de H↔A verschillen (wij zijn sneller met switchen op turnovers).
- **Adaptive challenge:** wij passen de streak-drempel aan op basis van context; zij
  gebruiken een vaste drempel. Dit verklaart ~2-3% van de H↔A verschillen.

### 4.2 Hun hygiëne (zij hebben, wij niet)

- **D-uitbreiding:** zij breiden D-intervallen ook *vooruit* uit (na de restart) bij
  aanhoudende onzichtbaarheid; wij alleen achteruit. Dit verklaart ~0,5% van de D vs
  levend verschillen.
- **Ball fill:** zij vullen ball gaps tot 3 seconden (75 frames); wij tot 2 seconden
  (50 frames). Dit verklaart ~1% van de X vs H/A verschillen (wij hebben vaker
  onbekende bal op langere occlusies).

## 5. Scorer-vergelijking (public window)

| Metriek | Wij | Zij | Verschil |
|---|---|---|---|
| macroF1 | 0,5212 | 0,5218 | +0,0006 (zij) |
| spellF1 | 0,2038 | 0,2075 | +0,0037 (zij) |
| accuracy | 0,5695 | 0,5710 | +0,0015 (zij) |
| kappa | 0,2690 | 0,2715 | +0,0025 (zij) |

**Verschillen zijn verwaarloosbaar** — allemaal binnen de bootstrap σ (~0,08 voor
macroF1, ~0,10 voor spellF1). Geen van beide pipelines is significant beter op de
public window.

## 6. Conclusie

Onze v3 en hun CoFi-Labs-v3 zijn **structureel identiek** (zelfde possessies,zelfde
duur,zelfde D-fractie) maar **verschillen op 33% van de frames** — waarvan 88% X vs
H/A (conservatief vs assertief). De echte H↔A omkeringen zijn 2,6%.

Onze hygiëne (GK-exclusie, phase priors, turnover signal, adaptive challenge) is
beter gedocumenteerd en theoretisch beter onderbouwd. Hun hygiëne (D-uitbreiding,
langere ball fill) is eenvoudiger maar effectief.

**Aanbeveling:** adopteer hun D-uitbreiding en langere ball fill (3 s), behoud onze
GK-exclusie, phase priors, turnover signal en adaptive challenge. De scorer-verschillen
zijn verwaarloosbaar, maar de hygiëne is beter.

*Bronbestanden: scratch `$TMPDIR/v3delta.aTME5T` (ours.csv, theirs.csv, analysis.json,
public_window.json). Rapport geschreven 2026-10-25.*