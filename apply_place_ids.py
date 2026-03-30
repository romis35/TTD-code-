"""
Load place_ids_from_user.txt and inject place_id into TTD JSON files
(TTDKLCC style: related_locations + operator.locations).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

BASE = Path(__file__).resolve().parent
MAP_FILE = BASE / "place_ids_from_user.txt"
OVERRIDE_FILE = BASE / "place_id_overrides.json"
TTD_FROM_CMS = BASE / "ttd_from_cms"
# Hand-maintained single-product feeds (skip ALL and merge script)
ROOT_TTD_GLOB = "TTD*.json"

# CMS / listing title -> exact key used in place_ids_from_user.txt
ALIASES: Dict[str, str] = {
    "Genting Highlands Premium Outlets Cable Car (Previously Known as Awana SkyWay)": "Awana SkyWay (Genting Cable Car)",
    "KL Hop On Hop Off Pass": "KL Hop On Hop Off",
    "Lost World Of Tambun Ipoh": "Lost World of Tambun",
    "A'famosa Melaka": "A'Famosa Melaka",
    "Monkey Splash Zone Water Park Ticket": "Monkey Splash Zone Water Park",
    "Kidzania Kuala Lumpur": "KidZania Kuala Lumpur",
    "Wet World Water Park Shah Alam": "Wet World Shah Alam",
    "SplashMania at Gamuda Cove, Selangor": "SplashMania (Gamuda Cove)",
    "Skyline Luge Kuala Lumpur": "Skyline Luge (Genting Highlands)",
    "Malaysia Heritage Studios in Melaka": "Malaysia Heritage Studios Melaka",
    "Zoo Teruntum Ticket in Kuantan": "Zoo Teruntum (Kuantan)",
    "Melaka Menara Taming Sari Tower": "Menara Taming Sari Tower (Melaka)",
    "[PROMO] SuperPark Malaysia": "SuperPark Malaysia (Kuala Lumpur)",
    "JDT Stadium Tour (Home Team Changing Room Closed for Renovation)": "JDT Hummer Tour",
    "Ice Skating Experience at IOI City Mall in Putrajaya": "IOI City Mall Ice Skating (Putrajaya)",
    "Teddyville Museum": "TeddyVille Museum",
    "Upside Down House Gallery Melaka Ticket": "Upside Down House Gallery Melaka",
    "The Top Penang": "The TOP Penang",
    "Big Bucket Splash Ticket at Gamuda Luge Gardens": "Big Bucket Splash (Gamuda Gardens)",
    "FunPark Gamuda Luge Gardens Ticket": "FunPark Gamuda Luge Gardens",
    "Hoverland at Wyndham Ion Majestic Hotel, Genting Highlands": "Hoverland Genting Highlands",
    "District 21 in IOI City Mall Putrajaya": "District 21 IOI City Mall",
    "Encore Melaka  Admission Ticket": "Encore Melaka",
    "Museum Of Illusions Kuala Lumpur": "Museum of Illusions KL",
    "Bayou Lagoon Water Park Ticket in Melaka": "Bayou Lagoon Water Park",
    "Firefly River Cruise Tour in Kota Tinggi Johor": "Firefly River Cruise Kota Tinggi",
    "Space & Time Cube": "immersify KL",
    "Singapore Oceanarium": "Aquaria KLCC",
    "Legong Dance Show Tickets at Ubud Palace Bali": "Ubud Palace (Legong Dance)",
    "SkyPark Observation Deck at Marina Bay Sands 滨海湾金沙空中花园": "SkyPark Marina Bay Sands",
    "Blue Ice Skating Rink @ KL East Mall": "Blue Ice Skating KL East Mall",
    "Blue Ice Skating Rink @ Paradigm Mall Johor Bahru": "Blue Ice Skating Paradigm JB",
    "Mangrove or Fireflies Tour in Bintan": "Mangrove / Fireflies Bintan",
    "Museum of Ice Cream Admission": "Museum of Ice Cream Singapore",
    "Ocean Dream Samudra at Ancol": "Ocean Dream Samudra Ancol",
    "KidZania SG": "KidZania Singapore",
    "Pangkor Giam Island Watersports": "Pangkor Watersports",
    "Eco Tourism Boat Tour Kampung Sungai Melayu": "Eco Tourism Sungai Melayu",
    "Melaka The Shore Sky Tower": "The Shore Sky Tower Melaka",
    "Tropical Spice Garden Entrance Tickets & Guided Tours": "Tropical Spice Garden Penang",
    "Langkawi Mangrove & Island Hopping Tours": "Langkawi Mangrove & Island Tours",
    "Langkawi Tanjung Rhu Mangrove Speedboat Tour": "Langkawi Mangrove Speedboat (Tanjung Rhu)",
    "Cameron Highlands and Mossy Forest Half Day Tour": "Cameron Highlands Tour",
    "SKYTREX Adventure Langkawi": "Skytrex Langkawi",
    "Lebam River Kayaking Adventure from Desaru , Johor": "Lebam River Kayaking Desaru",
    "Rumah Terbalik The Upside Down House of Borneo Ticket in Sabah": "Rumah Terbalik Sabah",
}


def load_place_map() -> Dict[str, str]:
    m: Dict[str, str] = {}
    text = MAP_FILE.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or "N/A" in line or "Not found" in line:
            continue
        if "\u2192" not in line:
            continue
        name, pid = [x.strip() for x in line.split("\u2192", 1)]
        if not pid.startswith("ChIJ"):
            continue
        m[name] = pid
    return m


def load_overrides() -> Dict[str, Dict[str, str]]:
    if not OVERRIDE_FILE.exists():
        return {"by_product_id": {}, "by_exact_title": {}}
    raw = json.loads(OVERRIDE_FILE.read_text(encoding="utf-8"))
    return {
        "by_product_id": {str(k): str(v) for k, v in (raw.get("by_product_id") or {}).items()},
        "by_exact_title": {str(k): str(v) for k, v in (raw.get("by_exact_title") or {}).items()},
    }


def simplify_title(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[\u200b\u00a0]", " ", s)
    s = re.sub(r"^\[PROMO\]\s*", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(
        r"\s+(Admission\s*)?Ticket(\s+in\s+[^,]+)?$",
        "",
        s,
        flags=re.I,
    )
    s = re.sub(r"\s+Pass$", "", s, flags=re.I)
    s = re.sub(r"\s+Ticket$", "", s, flags=re.I)
    return s.strip()


def norm_key(s: str) -> str:
    s = simplify_title(s).lower()
    s = s.replace("'", "'").replace("'", "'")
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def resolve_place_id(title: str, place_map: Dict[str, str]) -> Optional[str]:
    if not title or not title.strip():
        return None
    t = title.strip()
    if t in ALIASES:
        t = ALIASES[t]
    if t in place_map:
        return place_map[t]
    st = simplify_title(t)
    if st in place_map:
        return place_map[st]
    if st in ALIASES:
        k = ALIASES[st]
        if k in place_map:
            return place_map[k]
    nk = norm_key(t)
    for k, pid in place_map.items():
        if norm_key(k) == nk:
            return pid
    # substring: shortest map key contained in title (or title in key)
    best: Optional[tuple[int, str]] = None
    for k, pid in place_map.items():
        nk_k = norm_key(k)
        if len(nk_k) < 8:
            continue
        if nk_k in nk or nk in nk_k:
            score = min(len(nk), len(nk_k))
            if best is None or score > best[0]:
                best = (score, pid)
    return best[1] if best else None


def resolve_with_overrides(
    title: str,
    product_id: str,
    place_map: Dict[str, str],
    overrides: Dict[str, Dict[str, str]],
) -> Optional[str]:
    by_id = overrides.get("by_product_id") or {}
    if product_id and product_id in by_id:
        return by_id[product_id]
    by_title = overrides.get("by_exact_title") or {}
    for key, pid in by_title.items():
        if not pid.startswith("ChIJ"):
            continue
        if title == key or simplify_title(title) == simplify_title(key):
            return pid
    return resolve_place_id(title, place_map)


def related_with_place_id(place_id: str) -> List[dict]:
    # RelatedLocation.location wraps GeoLocation in an inner "location" (TTD feed spec).
    return [
        {
            "location": {"location": {"place_id": place_id}},
            "relation_type": "RELATION_TYPE_ADMISSION_TICKET",
        }
    ]


def apply_place_id_to_product(product: dict, place_id: str) -> None:
    rloc = related_with_place_id(place_id)
    for opt in product.get("options") or []:
        opt["related_locations"] = json.loads(json.dumps(rloc))
    op = product.get("operator")
    if op:
        op["locations"] = [{"location": {"place_id": place_id}}]


def process_file(
    path: Path,
    place_map: Dict[str, str],
    overrides: Dict[str, Dict[str, str]],
) -> tuple[bool, Optional[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    products = data.get("products") or []
    if not products:
        return False, "no products"
    title = (
        (products[0].get("title") or {})
        .get("localized_texts", [{}])[0]
        .get("text", "")
    )
    product_id = str((products[0].get("id") or "")).strip()
    pid = resolve_with_overrides(title, product_id, place_map, overrides)
    if not pid:
        return False, f"no place_id for title={title!r}"
    apply_place_id_to_product(products[0], pid)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True, None


def main() -> None:
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    place_map = load_place_map()
    if not place_map:
        raise SystemExit(f"No mappings in {MAP_FILE}")
    overrides = load_overrides()

    ok = skip = 0
    errs: List[str] = []

    if TTD_FROM_CMS.is_dir():
        for path in sorted(TTD_FROM_CMS.glob("TTD_*.json")):
            good, err = process_file(path, place_map, overrides)
            if good:
                ok += 1
            else:
                skip += 1
                errs.append(f"{path.name}: {err}")

    for path in sorted(BASE.glob(ROOT_TTD_GLOB)):
        name = path.name.upper()
        if name in ("TTD_ALL.JSON",) or path.name.startswith("_"):
            continue
        good, err = process_file(path, place_map, overrides)
        if good:
            ok += 1
        else:
            skip += 1
            errs.append(f"{path.name}: {err}")

    print(f"Updated {ok} files; skipped {skip}")
    for e in errs[:50]:
        print(f"  SKIP {e}")
    if len(errs) > 50:
        print(f"  ... {len(errs) - 50} more")


if __name__ == "__main__":
    main()
