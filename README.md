# Modifications — Description Builder (C411 / TORR9 / GF)

## Fichiers modifiés

- `src/trackers/C411.py`
- `src/trackers/GF.py`

---

## C411.py

### Suppression des fonctions externes

Les deux fonctions suivantes ont été supprimées et leur logique intégrée
directement dans `_build_description` :

- `_format_audio_bbcode(self, mi_text, meta)` — formatage BBCode des pistes audio
- `_format_subtitle_bbcode(self, mi_text, meta)` — formatage BBCode des sous-titres

---

### Pistes audio — logique inline

Le bloc de parsing audio est maintenant natif dans `_build_description`.

Améliorations apportées :

- Split basé sur `\n{2,}(?=Audio)` — capture correctement les pistes uniques sans numéro `#1`
- `AC-3` affiché `DD` au lieu de `AC3`
- Indication `(piste par défaut)` en minuscules
- Détection **Audio-Description** élargie :
  - `AD`, `[AD]`, `(AD)`
  - `Audiodescription`, `Audiodesc`
  - `Audio Description`, `Audio-Description`
  - `Descriptive`
- Détection des variantes françaises via `\b` (word boundary) dans le titre de piste ET le code de langue :
  - `VFF`, `VFQ`, `VFi`, `VF2`, `VOF`

Format de sortie audio :
```
🇫🇷 Français (piste par défaut) : DD 5.1 @ 384 kb/s
🇺🇸 Anglais : DDP 5.1 Atmos @ 768 kb/s
🇫🇷 Français Audio-Description : DD 5.1 @ 384 kb/s
```

---

### Pistes sous-titres — logique inline

Le bloc de parsing sous-titres est maintenant natif dans `_build_description`.

Améliorations apportées :

- Split basé sur `\n{2,}(?=Text)` — capture correctement les pistes uniques
- Détection de la **piste par défaut** (`Default : Yes`) en plus de la piste forcée
- Trois cas de mention combinée :
  - `(piste par défaut et forcée)`
  - `(piste par défaut)`
  - `(piste forcée)`
- Tags : `Forcés`, `Complets`, `SDH`
- Support des formats : `SRT`, `WEBVTT`, `PGS`, `ASS`
- Affichage du **nombre d'éléments** : `(X éléments)` via `Count of elements`

Format de sortie sous-titres :
```
🇫🇷 Français Forcés (piste par défaut et forcée) : SRT (49 éléments)
🇫🇷 Français Complets : SRT (858 éléments)
🇺🇸 Anglais Forcés (piste forcée) : SRT (2 éléments)
🇺🇸 Anglais Complets : SRT (823 éléments)
```

---

### Table de correspondance des langues

Ajout d'une table `_LANG_MAP` et d'une fonction `_resolve_lang` dans
`_build_description`. 35 langues mappées avec drapeau et nom français.

| Code | Drapeau | Nom français |
|------|---------|--------------|
| fr / fre / fra / french | 🇫🇷 | Français |
| en / eng / english | 🇺🇸 | Anglais |
| es / esp / spa / spanish | 🇪🇸 | Espagnol |
| de / ger / deu / german | 🇩🇪 | Allemand |
| it / ita / italian | 🇮🇹 | Italien |
| pt / por / portuguese | 🇵🇹 | Portugais |
| ja / jpn / japanese | 🇯🇵 | Japonais |
| ko / kor / korean | 🇰🇷 | Coréen |
| zh / chi / zho / chinese | 🇨🇳 | Chinois |
| ar / ara / arabic | 🇸🇦 | Arabe |
| ru / rus / russian | 🇷🇺 | Russe |
| nl / nld / dut / dutch | 🇳🇱 | Néerlandais |
| pl / pol / polish | 🇵🇱 | Polonais |
| tr / tur / turkish | 🇹🇷 | Turc |
| sv / swe / swedish | 🇸🇪 | Suédois |
| no / nor / norwegian | 🇳🇴 | Norvégien |
| da / dan / danish | 🇩🇰 | Danois |
| fi / fin / finnish | 🇫🇮 | Finnois |
| el / ell / gre / greek | 🇬🇷 | Grec |
| he / heb / hebrew | 🇮🇱 | Hébreu |
| hi / hin / hindi | 🇮🇳 | Hindi |
| th / tha / thai | 🇹🇭 | Thaï |
| vi / vie / vietnamese | 🇻🇳 | Vietnamien |
| id / ind / indonesian | 🇮🇩 | Indonésien |
| cs / cze / ces / czech | 🇨🇿 | Tchèque |
| hu / hun / hungarian | 🇭🇺 | Hongrois |
| ro / ron / rum / romanian | 🇷🇴 | Roumain |
| uk / ukr / ukrainian | 🇺🇦 | Ukrainien |

Fallback : toute langue non reconnue → `🌐 <nom brut MediaInfo>`

---

### En-têtes de section

Ajout d'une fonction `section_header(icon, title)` qui génère un séparateur
`━━━` suivi du titre centré. Les `SEP` redondants ont été supprimés.

Format :
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📝 Synopsis
```

Sections concernées :
- `📝 Synopsis`
- `ℹ️ Informations sur le titre`
- `🎭 Casting`
- `⚙️ Détails techniques`
- `✨ Information sur la release`
- `🖼️ Captures d'écran`
- `📝 Notes`

---

### Section "Information sur la release" — nouveaux champs

Ajout de deux champs :

- `📶 Débit global` — extrait de `Overall bit rate` dans le MediaInfo (section General)
- `📂 Nombre de fichier(s)` — déjà présent, alignement corrigé

Format :
```
💾 Taille totale : 3.76 GiB
📶 Débit global : 5 297 kb/s
📶 Débit vidéo : 3 817 kb/s
📂 Nombre de fichier(s) : 1
👥 Groupe : GROUP-NAME
```

---

## GF.py

### Ajout de `get_description`

GF hérite de UNIT3D qui utilise `DescriptionBuilder` par défaut. Un override
`get_description` a été ajouté pour déléguer à `C411._build_description` :

```python
async def get_description(self, meta: dict[str, Any]) -> dict[str, str]:
    from src.trackers.C411 import C411
    c411 = C411(config=self.config)
    desc = await c411._build_description(meta)
    return {"description": desc}
```

GF bénéficie ainsi de toutes les améliorations de C411 automatiquement.

---

## TORR9.py

Aucune modification nécessaire. TORR9 délègue déjà à `C411._build_description`
via son propre `_build_description`, toutes les améliorations s'appliquent
automatiquement.
