#!/usr/bin/env python3
"""Estrae agenzie/onoranze funebri a Roma via Google Places API (Legacy)."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RETRYABLE_PLACES_STATUSES = {"OVER_QUERY_LIMIT", "UNKNOWN_ERROR"}
QUERIES = ("agenzia funebre Roma", "onoranze funebri Roma")


@dataclass
class PlaceRecord:
    cap: str
    name: str
    place_id: str
    formatted_address: str
    phone: str
    website: str
    maps_url: str
    maybe_not_rome: bool


def load_env_file(path: Path = Path('.env')) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            continue
        key, value = stripped.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


class GooglePlacesClient:
    def __init__(self, api_key: str, timeout_sec: int = 20, max_retries: int = 5) -> None:
        self.api_key = api_key
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries

    def _request(self, url: str, params: dict[str, str], context: str) -> dict[str, Any]:
        attempt = 0
        backoff = 1.0
        query_url = f"{url}?{urlencode(params)}"
        while True:
            attempt += 1
            try:
                with urlopen(query_url, timeout=self.timeout_sec) as response:
                    status_code = getattr(response, 'status', 200)
                    body = response.read().decode('utf-8')
            except HTTPError as exc:
                status_code = exc.code
                if status_code in RETRYABLE_STATUS_CODES and attempt <= self.max_retries:
                    logging.warning("%s: HTTP %s, retry tra %.1fs", context, status_code, backoff)
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise RuntimeError(f"{context}: HTTP {status_code}") from exc
            except URLError as exc:
                if attempt <= self.max_retries:
                    logging.warning("%s: errore rete (%s), retry tra %.1fs", context, exc, backoff)
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise RuntimeError(f"{context}: errore rete definitivo: {exc}") from exc

            if status_code in RETRYABLE_STATUS_CODES:
                if attempt <= self.max_retries:
                    logging.warning("%s: HTTP %s, retry tra %.1fs", context, status_code, backoff)
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise RuntimeError(f"{context}: HTTP {status_code} dopo {self.max_retries} tentativi")

            payload = json.loads(body)
            status = payload.get('status', '')
            if status in RETRYABLE_PLACES_STATUSES:
                if attempt <= self.max_retries:
                    logging.warning("%s: Places status %s, retry tra %.1fs", context, status, backoff)
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise RuntimeError(f"{context}: Places status {status} dopo {self.max_retries} tentativi")
            return payload

    def text_search(self, query: str) -> list[dict[str, Any]]:
        logging.info("Ricerca Text Search: '%s'", query)
        places: list[dict[str, Any]] = []
        next_page_token: str | None = None
        page_num = 0

        while True:
            page_num += 1
            params: dict[str, str] = {'key': self.api_key, 'query': query}
            if next_page_token:
                params = {'key': self.api_key, 'pagetoken': next_page_token}

            payload = self._request(TEXT_SEARCH_URL, params, f'text_search:{query}:page_{page_num}')
            status = payload.get('status')
            if status not in {'OK', 'ZERO_RESULTS'}:
                logging.error('Text Search status inatteso: %s (query=%s)', status, query)
                break

            results = payload.get('results', [])
            places.extend(results)
            logging.info("Query '%s' pagina %s: +%s risultati", query, page_num, len(results))

            next_page_token = payload.get('next_page_token')
            if not next_page_token:
                break
            logging.info('next_page_token presente, attendo 2.5s...')
            time.sleep(2.5)

        return places

    def place_details(self, place_id: str) -> dict[str, Any] | None:
        fields = ','.join([
            'name',
            'place_id',
            'formatted_address',
            'address_component',
            'website',
            'formatted_phone_number',
            'url',
        ])
        params = {'key': self.api_key, 'place_id': place_id, 'fields': fields}
        payload = self._request(DETAILS_URL, params, f'details:{place_id}')
        status = payload.get('status')
        if status == 'OK':
            return payload.get('result', {})
        if status == 'NOT_FOUND':
            logging.warning('Place details non trovato per place_id=%s', place_id)
            return None
        logging.error('Place details fallito per %s, status=%s', place_id, status)
        return None


def extract_postal_code(address_components: list[dict[str, Any]]) -> str:
    for component in address_components:
        if 'postal_code' in component.get('types', []):
            return component.get('long_name') or 'CAP_NON_TROVATO'
    return 'CAP_NON_TROVATO'


def is_probably_rome(formatted_address: str, address_components: list[dict[str, Any]]) -> bool:
    if 'roma' in formatted_address.lower():
        return True
    for component in address_components:
        if 'locality' in component.get('types', []) and component.get('long_name', '').strip().lower() == 'roma':
            return True
    return False


def has_website_value(website: Any) -> bool:
    return isinstance(website, str) and website.strip() != ''


def write_csv(records: list[PlaceRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=['cap', 'name', 'place_id', 'formatted_address', 'phone', 'website', 'maps_url', 'maybe_not_rome'],
        )
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))


def write_json_by_cap(records: list[PlaceRecord], output_path: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record.cap, []).append(asdict(record))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(grouped, ensure_ascii=False, indent=2), encoding='utf-8')
    return grouped


def write_cap_summary(grouped: dict[str, list[dict[str, Any]]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=['cap', 'numero_attivita'])
        writer.writeheader()
        for cap in sorted(grouped.keys()):
            writer.writerow({'cap': cap, 'numero_attivita': len(grouped[cap])})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Estrazione agenzie funebri Roma senza sito web')
    parser.add_argument('--limit', type=int, default=None, help='Numero massimo di attività da salvare (es. 100)')
    parser.add_argument('--csv-name', default='agenzie_funebri_roma_no_sito.csv', help='Nome del CSV principale in OUTPUT_DIR')
    return parser


def main() -> None:
    args = build_parser().parse_args()
    load_env_file()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

    api_key = os.getenv('GOOGLE_MAPS_API_KEY', '').strip()
    if not api_key:
        raise RuntimeError('GOOGLE_MAPS_API_KEY non configurata nel file .env o nelle variabili ambiente')

    output_dir = Path(os.getenv('OUTPUT_DIR', 'output')).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    client = GooglePlacesClient(api_key=api_key)
    discovered_place_ids: set[str] = set()
    for query in QUERIES:
        for place in client.text_search(query):
            place_id = place.get('place_id')
            if isinstance(place_id, str) and place_id:
                discovered_place_ids.add(place_id)
    logging.info('Totale place_id unici raccolti da Text Search: %s', len(discovered_place_ids))

    selected_records: list[PlaceRecord] = []
    total = len(discovered_place_ids)
    for idx, place_id in enumerate(sorted(discovered_place_ids), start=1):
        details = client.place_details(place_id)
        if not details:
            continue

        formatted_address = details.get('formatted_address') or ''
        address_components = details.get('address_components') or []
        website = details.get('website') or ''

        if has_website_value(website):
            logging.info('[%s/%s] Scartata (website presente): %s', idx, total, place_id)
            continue

        selected_records.append(
            PlaceRecord(
                cap=extract_postal_code(address_components),
                name=(details.get('name') or '').strip(),
                place_id=details.get('place_id') or place_id,
                formatted_address=formatted_address,
                phone=(details.get('formatted_phone_number') or '').strip(),
                website='',
                maps_url=(details.get('url') or '').strip(),
                maybe_not_rome=not is_probably_rome(formatted_address, address_components),
            )
        )
        logging.info('[%s/%s] Tenuta (no website). Totale selezionate: %s', idx, total, len(selected_records))

        if args.limit and len(selected_records) >= args.limit:
            logging.info('Raggiunto limit=%s, interrompo la scansione.', args.limit)
            break

    selected_records.sort(key=lambda r: (r.cap, r.name.lower(), r.place_id))

    csv_path = output_dir / args.csv_name
    json_path = output_dir / 'agenzie_funebri_roma_no_sito_by_cap.json'
    summary_path = output_dir / 'by_cap_summary.csv'

    write_csv(selected_records, csv_path)
    grouped = write_json_by_cap(selected_records, json_path)
    write_cap_summary(grouped, summary_path)

    logging.info('Esportazione completata.')
    logging.info('CSV: %s', csv_path)
    logging.info('JSON: %s', json_path)
    logging.info('Summary CSV: %s', summary_path)
    logging.info('Totale attività senza sito: %s', len(selected_records))


if __name__ == '__main__':
    main()
