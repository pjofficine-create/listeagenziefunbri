#!/usr/bin/env python3
"""Estrae agenzie/onoranze funebri a Roma via Google Places API (Legacy).

Esempio output CSV (prime 5 righe):
# cap,name,place_id,formatted_address,phone,website,maps_url,maybe_not_rome
# 00184,Agenzia Funebre Esempio,ChIJ123...,Via Esempio 1, Roma RM,+39 06 1234567,,https://maps.google.com/?cid=123,false
# 00185,Onoranze Funebri Demo,ChIJ456...,Via Demo 10, Roma RM,+39 06 7654321,,https://maps.google.com/?cid=456,false
# 00146,Servizi Funebri Test,ChIJ789...,Via Test 20, Roma RM,, ,https://maps.google.com/?cid=789,true
# CAP_NON_TROVATO,Agenzia Alfa,ChIJABC...,Indirizzo non completo,+39 06 1111111,,https://maps.google.com/?cid=111,true
# 00192,Agenzia Beta,ChIJDEF...,Via Beta 7, Roma RM,, ,https://maps.google.com/?cid=222,false
"""

from __future__ import annotations

import csv
import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

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


class GooglePlacesClient:
    def __init__(self, api_key: str, timeout_sec: int = 20, max_retries: int = 5) -> None:
        self.api_key = api_key
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries
        self.session = requests.Session()

    def _request(self, url: str, params: dict[str, str], context: str) -> dict[str, Any]:
        attempt = 0
        backoff = 1.0

        while True:
            attempt += 1
            try:
                response = self.session.get(url, params=params, timeout=self.timeout_sec)
            except requests.RequestException as exc:
                if attempt > self.max_retries:
                    raise RuntimeError(f"{context}: errore rete definitivo: {exc}") from exc
                logging.warning("%s: errore rete (%s), retry tra %.1fs", context, exc, backoff)
                time.sleep(backoff)
                backoff *= 2
                continue

            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt > self.max_retries:
                    raise RuntimeError(
                        f"{context}: HTTP {response.status_code} dopo {self.max_retries} tentativi"
                    )
                logging.warning(
                    "%s: HTTP %s, retry tra %.1fs",
                    context,
                    response.status_code,
                    backoff,
                )
                time.sleep(backoff)
                backoff *= 2
                continue

            response.raise_for_status()
            payload = response.json()
            status = payload.get("status", "")

            if status in RETRYABLE_PLACES_STATUSES:
                if attempt > self.max_retries:
                    raise RuntimeError(
                        f"{context}: Places status {status} dopo {self.max_retries} tentativi"
                    )
                logging.warning("%s: Places status %s, retry tra %.1fs", context, status, backoff)
                time.sleep(backoff)
                backoff *= 2
                continue

            return payload

    def text_search(self, query: str) -> list[dict[str, Any]]:
        logging.info("Ricerca Text Search: '%s'", query)
        places: list[dict[str, Any]] = []
        next_page_token: str | None = None
        page_num = 0

        while True:
            page_num += 1
            params: dict[str, str] = {"key": self.api_key, "query": query}
            if next_page_token:
                params = {"key": self.api_key, "pagetoken": next_page_token}

            payload = self._request(TEXT_SEARCH_URL, params, f"text_search:{query}:page_{page_num}")
            status = payload.get("status")

            if status not in {"OK", "ZERO_RESULTS"}:
                logging.error("Text Search status inatteso: %s (query=%s)", status, query)
                break

            results = payload.get("results", [])
            places.extend(results)
            logging.info("Query '%s' pagina %s: +%s risultati", query, page_num, len(results))

            next_page_token = payload.get("next_page_token")
            if not next_page_token:
                break

            logging.info("next_page_token presente, attendo 2.5s...")
            time.sleep(2.5)

        return places

    def place_details(self, place_id: str) -> dict[str, Any] | None:
        fields = ",".join(
            [
                "name",
                "place_id",
                "formatted_address",
                "address_component",
                "website",
                "formatted_phone_number",
                "url",
            ]
        )
        params = {"key": self.api_key, "place_id": place_id, "fields": fields}
        payload = self._request(DETAILS_URL, params, f"details:{place_id}")
        status = payload.get("status")

        if status == "OK":
            return payload.get("result", {})

        if status == "NOT_FOUND":
            logging.warning("Place details non trovato per place_id=%s", place_id)
            return None

        logging.error("Place details fallito per %s, status=%s", place_id, status)
        return None


def extract_postal_code(address_components: list[dict[str, Any]]) -> str:
    for component in address_components:
        types = component.get("types", [])
        if "postal_code" in types:
            return component.get("long_name") or "CAP_NON_TROVATO"
    return "CAP_NON_TROVATO"


def is_probably_rome(formatted_address: str, address_components: list[dict[str, Any]]) -> bool:
    if "roma" in formatted_address.lower():
        return True

    for component in address_components:
        types = component.get("types", [])
        if "locality" in types and component.get("long_name", "").strip().lower() == "roma":
            return True
    return False


def has_website_value(website: Any) -> bool:
    return isinstance(website, str) and website.strip() != ""


def write_csv(records: list[PlaceRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "cap",
                "name",
                "place_id",
                "formatted_address",
                "phone",
                "website",
                "maps_url",
                "maybe_not_rome",
            ],
        )
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))


def write_json_by_cap(records: list[PlaceRecord], output_path: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record.cap, []).append(asdict(record))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(grouped, fh, ensure_ascii=False, indent=2)

    return grouped


def write_cap_summary(grouped: dict[str, list[dict[str, Any]]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["cap", "numero_attivita"])
        writer.writeheader()
        for cap in sorted(grouped.keys()):
            writer.writerow({"cap": cap, "numero_attivita": len(grouped[cap])})


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY non configurata nel file .env")

    output_dir = Path(os.getenv("OUTPUT_DIR", "output")).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    client = GooglePlacesClient(api_key=api_key)

    discovered_place_ids: set[str] = set()
    for query in QUERIES:
        for place in client.text_search(query):
            place_id = place.get("place_id")
            if isinstance(place_id, str) and place_id:
                discovered_place_ids.add(place_id)

    logging.info("Totale place_id unici raccolti da Text Search: %s", len(discovered_place_ids))

    selected_records: list[PlaceRecord] = []

    for idx, place_id in enumerate(sorted(discovered_place_ids), start=1):
        details = client.place_details(place_id)
        if not details:
            continue

        formatted_address = details.get("formatted_address") or ""
        address_components = details.get("address_components") or []
        website = details.get("website") or ""

        maybe_not_rome = not is_probably_rome(formatted_address, address_components)

        if has_website_value(website):
            logging.info("[%s/%s] Scartata (website presente): %s", idx, len(discovered_place_ids), place_id)
            continue

        record = PlaceRecord(
            cap=extract_postal_code(address_components),
            name=(details.get("name") or "").strip(),
            place_id=details.get("place_id") or place_id,
            formatted_address=formatted_address,
            phone=(details.get("formatted_phone_number") or "").strip(),
            website="",
            maps_url=(details.get("url") or "").strip(),
            maybe_not_rome=maybe_not_rome,
        )
        selected_records.append(record)

        logging.info(
            "[%s/%s] Tenuta (no website). Totale selezionate: %s",
            idx,
            len(discovered_place_ids),
            len(selected_records),
        )

    selected_records.sort(key=lambda r: (r.cap, r.name.lower(), r.place_id))

    csv_path = output_dir / "agenzie_funebri_roma_no_sito.csv"
    json_path = output_dir / "agenzie_funebri_roma_no_sito_by_cap.json"
    summary_path = output_dir / "by_cap_summary.csv"

    write_csv(selected_records, csv_path)
    grouped = write_json_by_cap(selected_records, json_path)
    write_cap_summary(grouped, summary_path)

    logging.info("Esportazione completata.")
    logging.info("CSV: %s", csv_path)
    logging.info("JSON: %s", json_path)
    logging.info("Summary CSV: %s", summary_path)
    logging.info("Totale attività senza sito: %s", len(selected_records))


if __name__ == "__main__":
    main()
