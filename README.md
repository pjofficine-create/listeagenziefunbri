# Estrazione agenzie funebri a Roma senza sito web (Google Places API)

Script Python 3 che usa **solo API ufficiali Google Places (Legacy REST)** per:

1. Cercare attività con query `agenzia funebre Roma` e `onoranze funebri Roma`.
2. Recuperare Place Details per ogni `place_id` trovato.
3. Filtrare solo attività con campo `website` mancante/vuoto.
4. Raggruppare per CAP.
5. Esportare CSV + JSON + CSV di riepilogo per CAP.

## Requisiti

- Python 3.10+
- Google Cloud project con billing attivo.
- API Places API (Legacy) abilitata.
- API key valida.
- Nessuna libreria esterna obbligatoria (usa solo standard library).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
# opzionale: pip install -r requirements.txt (nessuna dipendenza esterna)
```

Crea `.env` nella root:

```env
GOOGLE_MAPS_API_KEY=la_tua_api_key
OUTPUT_DIR=output
```

## Esecuzione

Esecuzione standard:

```bash
python main.py
```

Per ottenere massimo 100 record nel CSV principale:

```bash
python main.py --limit 100 --csv-name agenzie_funebri_roma_no_sito_100.csv
```

## Output

In `OUTPUT_DIR` vengono generati:

- CSV principale (`agenzie_funebri_roma_no_sito.csv` o quello passato via `--csv-name`)
- `agenzie_funebri_roma_no_sito_by_cap.json`
- `by_cap_summary.csv`

Colonne CSV:

`cap, name, place_id, formatted_address, phone, website, maps_url, maybe_not_rome`

## Note implementative

- Paginazione Text Search con `next_page_token` e attesa 2.5 secondi.
- Deduplica su `place_id`.
- Place Details fields: `name, place_id, formatted_address, address_component, website, formatted_phone_number, url`.
- CAP da `postal_code`; fallback `CAP_NON_TROVATO`.
- Record fuori Roma: mantenuti con flag `maybe_not_rome=true` se non è verificabile `Roma` in indirizzo/locality.
- Retry con backoff su HTTP 429/5xx e status Places `OVER_QUERY_LIMIT`, `UNKNOWN_ERROR`.

## Esempio output (prime 5 righe) in commento

```csv
# cap,name,place_id,formatted_address,phone,website,maps_url,maybe_not_rome
# 00184,Agenzia Funebre Esempio,ChIJ123...,Via Esempio 1, Roma RM,+39 06 1234567,,https://maps.google.com/?cid=123,false
# 00185,Onoranze Funebri Demo,ChIJ456...,Via Demo 10, Roma RM,+39 06 7654321,,https://maps.google.com/?cid=456,false
# 00146,Servizi Funebri Test,ChIJ789...,Via Test 20, Roma RM,, ,https://maps.google.com/?cid=789,true
# CAP_NON_TROVATO,Agenzia Alfa,ChIJABC...,Indirizzo non completo,+39 06 1111111,,https://maps.google.com/?cid=111,true
# 00192,Agenzia Beta,ChIJDEF...,Via Beta 7, Roma RM,, ,https://maps.google.com/?cid=222,false
```
