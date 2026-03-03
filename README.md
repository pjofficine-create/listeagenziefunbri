# Estrazione agenzie funebri a Roma senza sito web (Google Places API)

Script Python 3 "production-ready" che usa **solo API ufficiali Google Places (Legacy REST)** per:

1. Cercare attività con query `agenzia funebre Roma` e `onoranze funebri Roma`.
2. Recuperare Place Details per ogni `place_id` trovato.
3. Filtrare solo attività con campo `website` mancante/vuoto.
4. Raggruppare per CAP.
5. Esportare CSV + JSON + CSV di riepilogo per CAP.

## Requisiti

- Python 3.10+
- Un progetto Google Cloud con:
  - **Billing attivo**
  - API abilitate:
    - Places API (Legacy)
- API key valida con restrizioni adeguate (consigliato).

## Setup

1. Clona o copia il progetto.
2. Crea ambiente virtuale e installa dipendenze:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Crea file `.env` nella root:

```env
GOOGLE_MAPS_API_KEY=la_tua_api_key
OUTPUT_DIR=output
```

> `OUTPUT_DIR` è opzionale (default: `output`).

## Esecuzione

```bash
python main.py
```

## Output generati

Nella cartella `OUTPUT_DIR`:

- `agenzie_funebri_roma_no_sito.csv`
- `agenzie_funebri_roma_no_sito_by_cap.json`
- `by_cap_summary.csv`

### Colonne CSV principale

`cap, name, place_id, formatted_address, phone, website, maps_url, maybe_not_rome`

> Nota: il requisito iniziale chiedeva queste colonne senza `maybe_not_rome`, ma è stato aggiunto per tracciare i casi dubbi come richiesto dalle note.

## Logica principale implementata

- **Paginazione Text Search** con `next_page_token` e attesa 2.5s prima della pagina successiva.
- **Deduplica** globale su `place_id`.
- **Place Details** con campi minimi richiesti:
  - `name, place_id, formatted_address, address_component, website, formatted_phone_number, url`
- **Estrazione CAP** da `address_components` cercando `postal_code`, fallback a `CAP_NON_TROVATO`.
- **Filtro no-sito**: tiene solo record con `website` vuoto/null.
- **Filtro Roma (regola semplice)**:
  - considera Roma se `formatted_address` contiene `Roma` oppure `locality=Roma`.
  - se non certo, **mantiene** il record e imposta `maybe_not_rome=true`.
- **Resilienza errori/rate limit**:
  - retry con exponential backoff su HTTP `429/5xx` e Places status `OVER_QUERY_LIMIT`, `UNKNOWN_ERROR`.
- **Progress logging**: conteggi trovate/scartate/tenute.

## Esempio output (prime 5 righe) in commento

```csv
# cap,name,place_id,formatted_address,phone,website,maps_url,maybe_not_rome
# 00184,Agenzia Funebre Esempio,ChIJ123...,Via Esempio 1, Roma RM,+39 06 1234567,,https://maps.google.com/?cid=123,false
# 00185,Onoranze Funebri Demo,ChIJ456...,Via Demo 10, Roma RM,+39 06 7654321,,https://maps.google.com/?cid=456,false
# 00146,Servizi Funebri Test,ChIJ789...,Via Test 20, Roma RM,, ,https://maps.google.com/?cid=789,true
# CAP_NON_TROVATO,Agenzia Alfa,ChIJABC...,Indirizzo non completo,+39 06 1111111,,https://maps.google.com/?cid=111,true
# 00192,Agenzia Beta,ChIJDEF...,Via Beta 7, Roma RM,, ,https://maps.google.com/?cid=222,false
```

## Note operative

- Nessuno scraping HTML di Google Maps.
- Se `website` è valorizzato, viene considerato **presente** senza inferenze.
- È possibile adattare facilmente query/città modificando la costante `QUERIES` in `main.py`.
