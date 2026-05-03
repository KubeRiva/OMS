"""Geocoding utility using Nominatim (OpenStreetMap) — no API key required."""
import logging
import httpx

logger = logging.getLogger(__name__)

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_HEADERS = {"User-Agent": "OMS/1.0 (order-management-system)"}


async def geocode_address(
    postal_code: str,
    city: str = "",
    state: str = "",
    country: str = "US",
) -> tuple[float, float] | None:
    """
    Return (latitude, longitude) for a shipping address.

    Tries a detailed query first (city + state + zip), then falls back to
    zip-only if the first attempt returns no results.
    Returns None if geocoding fails or times out.
    """
    queries = []
    if city and state and postal_code:
        queries.append(f"{city}, {state} {postal_code}, {country}")
    if postal_code:
        queries.append(postal_code)

    try:
        async with httpx.AsyncClient(timeout=5.0, headers=_HEADERS) as client:
            for q in queries:
                resp = await client.get(
                    _NOMINATIM_URL,
                    params={"q": q, "format": "json", "limit": 1, "countrycodes": country.lower()},
                )
                resp.raise_for_status()
                data = resp.json()
                if data:
                    lat = float(data[0]["lat"])
                    lon = float(data[0]["lon"])
                    logger.info(f"Geocoded '{q}' → ({lat:.4f}, {lon:.4f})")
                    return lat, lon
    except httpx.TimeoutException:
        logger.warning(f"Geocoding timed out for postal_code={postal_code}")
    except Exception as exc:
        logger.warning(f"Geocoding failed for postal_code={postal_code}: {exc}")

    return None
