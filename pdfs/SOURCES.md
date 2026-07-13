# Diet & Nutrition PDF Sources

This file lists the recommended diet and nutrition PDF sources to download into
`pdfs/` to improve answer quality for nutrition-focused questions after stroke.

After downloading any file here, rebuild the index:

```bash
rm -f .rag/index.json .rag/embedding_cache.json
source venv/bin/activate
python app.py
# Click Ingest in the UI, or POST /ingest
```

---

## Tier 1 — Clinical Guidelines (highest priority)

| Expected filename | Publisher | URL | Covers |
|-------------------|-----------|-----|--------|
| `Stroke-Foundation-Clinical-Guidelines-Nutrition-2023.pdf` | Stroke Foundation (Australia) | https://informme.org.au/guidelines/living-clinical-guidelines-for-stroke-management | Dysphagia, malnutrition screening, oral feeding, tube feeding, hydration |
| `ESPEN-Guideline-Clinical-Nutrition-Neurology-2021.pdf` | ESPEN (European Society for Clinical Nutrition) | https://www.clinicalnutritionjournal.com/article/S0261-5614(21)00232-4/fulltext | Post-stroke malnutrition, early nutrition, tube feeding, dysphagia diets |
| `AHA-Dietary-Recommendations-Stroke-Prevention.pdf` | American Heart Association | https://www.ahajournals.org/doi/10.1161/CIR.0000000000000767 | Sodium, saturated fat, Mediterranean/DASH diet patterns |
| `SIGN-118-Stroke-Rehabilitation-Nutrition.pdf` | SIGN (Scottish Intercollegiate Guidelines Network) | https://www.sign.ac.uk/our-guidelines/management-of-patients-with-stroke-rehabilitation/ | Nutritional assessment, feeding support, texture modification |

---

## Tier 2 — Public Health / Patient Guides

| Expected filename | Publisher | URL | Covers |
|-------------------|-----------|-----|--------|
| `AHA-Heart-Healthy-Eating-After-Stroke.pdf` | American Heart Association | https://www.heart.org/en/health-topics/stroke | Mediterranean, DASH, sodium, saturated fat, practical food swaps |
| `Stroke-Association-UK-Eating-Well-After-Stroke.pdf` | Stroke Association (UK) | https://www.stroke.org.uk/resources | Everyday diet, salt, fat, fruit/veg, weight management, dietitian referral |
| `IDDSI-Framework-Texture-Modified-Foods.pdf` | IDDSI (International Dysphagia Diet Standardisation Initiative) | https://iddsi.org/Framework | Texture levels 0–7, thickened liquids, food preparation safety |
| `Heart-Stroke-Canada-Nutrition-After-Stroke.pdf` | Heart and Stroke Foundation Canada | https://www.heartandstroke.ca/stroke | Post-stroke eating, hydration, diabetes/hypertension diet overlap |

---

## Tier 3 — Peer-Reviewed Reviews

| Expected filename | Journal | URL | Covers |
|-------------------|---------|-----|--------|
| `Cochrane-Nutritional-Support-After-Stroke.pdf` | Cochrane Database | https://www.cochranelibrary.com | Early enteral nutrition, route, timing, outcomes |
| `Mediterranean-Diet-Stroke-Risk-Meta-Analysis.pdf` | Stroke / Neurology | PubMed open access | Mediterranean diet adherence, primary and secondary stroke prevention |
| `DASH-Diet-Stroke-Cardiovascular-Risk.pdf` | JAMA / Hypertension | PubMed open access | Blood pressure reduction, sodium, stroke incidence reduction |

---

## Corpus Gap Coverage

| Patient Question | Tier 1 Source | Tier 2 Source |
|---|---|---|
| What should I eat after a stroke? | AHA dietary guidelines | AHA/Stroke Association patient guides |
| Is the Mediterranean diet good after stroke? | AHA dietary guidelines | Mediterranean diet review |
| How much sodium/salt is safe? | AHA dietary guidelines | AHA patient guide |
| I have trouble swallowing — what can I eat? | Stroke Foundation, ESPEN | IDDSI framework |
| How much water should I drink? | Stroke Foundation, ESPEN | Heart & Stroke Canada |
| I also have diabetes — what should I eat? | ESPEN neurology guideline | Heart & Stroke Canada |
| When should I see a dietitian? | Stroke Foundation, SIGN 118 | Stroke Association UK |
