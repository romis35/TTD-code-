"""Merge TTD JSON feeds; normalize each product to TTDKLCC.json shape."""
import copy
import json
import re
from pathlib import Path
from typing import Optional

BASE = Path(__file__).resolve().parent
FILES = [
    "TTD.json",
    "TTD2.json",
    "TTDBTS.json",
    "TTDDF.json",
    "TTDEP.json",
    "TTDFGL.json",
    "TTDG.json",
    "TTDGPOC.json",
    "TTDKLCC.json",
    "TTDL.json",
    "TTDLCC.json",
    "TTDMHS.json",
    "TTDS.json",
    "TTDU.json",
]
OUT = BASE / "TTD_ALL.json"


def html_to_plain(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return " ".join(s.split())


def flatten_localized(obj) -> str:
    if not obj:
        return ""
    texts = obj.get("localized_texts") or []
    parts = []
    for t in texts:
        parts.append(t.get("text") or "")
    return html_to_plain(" ".join(parts).strip())


def extract_place_id_from_related_location(rl: dict) -> Optional[str]:
    if not isinstance(rl, dict):
        return None
    loc = rl.get("location") or {}
    inner = loc.get("location") or {}
    if isinstance(inner, dict):
        if "place_id" in inner:
            return inner["place_id"]
        pi = inner.get("place_info") or {}
        if isinstance(pi, dict) and "place_id" in pi:
            return pi["place_id"]
    if isinstance(loc, dict) and "place_id" in loc:
        return loc["place_id"]
    return None


def first_place_id_in_options(options: list) -> Optional[str]:
    for opt in options or []:
        for rl in opt.get("related_locations") or []:
            pid = extract_place_id_from_related_location(rl)
            if pid:
                return pid
    return None


def normalize_related_location(rl: dict) -> dict:
    pid = extract_place_id_from_related_location(rl)
    if pid:
        # Per TTD feed spec: RelatedLocation.location is Location{ location: GeoLocation{ place_id } }.
        return {
            "location": {"location": {"place_id": pid}},
            "relation_type": rl.get("relation_type", "RELATION_TYPE_ADMISSION_TICKET"),
        }
    rl = copy.deepcopy(rl)
    loc = rl.get("location") or {}
    loc.pop("description", None)
    inner = loc.get("location")
    if isinstance(inner, dict):
        inner.pop("description", None)
    return rl


def get_place_id_from_operator_location(loc_item: dict) -> Optional[str]:
    if not isinstance(loc_item, dict):
        return None
    loc = loc_item.get("location") or {}
    if not isinstance(loc, dict):
        return None
    inner = loc.get("location")
    if isinstance(inner, dict):
        if "place_id" in inner:
            return inner["place_id"]
        pi = inner.get("place_info") or {}
        if isinstance(pi, dict) and "place_id" in pi:
            return pi["place_id"]
    if "place_id" in loc:
        return loc["place_id"]
    pi = loc.get("place_info") or {}
    if isinstance(pi, dict) and "place_id" in pi:
        return pi["place_id"]
    return None


def normalize_operator(product: dict, place_id_fallback: Optional[str]) -> Optional[dict]:
    op = product.get("operator")
    if not op:
        return None
    pid = None
    for loc_item in op.get("locations") or []:
        pid = get_place_id_from_operator_location(loc_item)
        if pid:
            break
    if not pid:
        pid = place_id_fallback
    out = {}
    # Operator display / GBP: prefer `name`, else migrate from google_business_profile_name.
    src = None
    if "name" in op:
        src = copy.deepcopy(op["name"])
    elif "google_business_profile_name" in op:
        src = copy.deepcopy(op["google_business_profile_name"])
    if isinstance(src, dict):
        for t in src.get("localized_texts") or []:
            txt = t.get("text")
            if isinstance(txt, str):
                t["text"] = txt.replace("™", "").replace("®", "").strip()
        out["name"] = copy.deepcopy(src)
        # Merchant Center operator module still expects google_business_profile_name; mirror `name`.
        out["google_business_profile_name"] = copy.deepcopy(src)
    pn = op.get("phone_number")
    if isinstance(pn, str) and pn.strip():
        out["phone_number"] = pn.strip()
    # Operator Location uses GeoLocation directly under Location (flat place_id), per partner template.
    if pid:
        out["locations"] = [{"location": {"place_id": pid}}]
    else:
        cleaned = []
        for loc_item in op.get("locations") or []:
            li = copy.deepcopy(loc_item)
            li.pop("description", None)
            cleaned.append(li)
        out["locations"] = cleaned
    return out


def option_title_text(opt: dict) -> str:
    return flatten_localized(opt.get("title")) or opt.get("id", "")


def collect_option_extras_for_features(opt: dict) -> list:
    """Move fields dropped from KLCC-style options into product_features."""
    extra = []
    desc = flatten_localized(opt.get("description"))
    if desc:
        extra.append(
            {
                "feature_type": "TEXT_FEATURE_MUST_KNOW",
                "value": {
                    "localized_texts": [
                        {
                            "language_code": "en",
                            "text": f"{option_title_text(opt)}: {desc}",
                        }
                    ]
                },
            }
        )
    for feat in opt.get("option_features") or []:
        extra.append(copy.deepcopy(feat))
    mp = opt.get("meeting_point")
    if mp:
        mtxt = flatten_localized(mp.get("description"))
        if not mtxt:
            loc = (mp.get("location") or {}).get("place_info") or {}
            mtxt = loc.get("name") or loc.get("unstructured_address") or ""
        if mtxt:
            extra.append(
                {
                    "feature_type": "TEXT_FEATURE_MUST_KNOW",
                    "value": {
                        "localized_texts": [
                            {
                                "language_code": "en",
                                "text": f"{option_title_text(opt)} — Meeting point: {html_to_plain(mtxt)}",
                            }
                        ]
                    },
                }
            )
    dur = opt.get("duration_sec")
    if isinstance(dur, int) and dur > 0:
        hours = dur / 3600
        label = f"{hours:g} hours" if hours >= 1 else f"{dur // 60} minutes"
        extra.append(
            {
                "feature_type": "TEXT_FEATURE_MUST_KNOW",
                "value": {
                    "localized_texts": [
                        {
                            "language_code": "en",
                            "text": f"{option_title_text(opt)} — Duration: {label}",
                        }
                    ]
                },
            }
        )
    return extra


def normalize_option(opt: dict) -> dict:
    out = {
        "id": opt["id"],
        "title": opt["title"],
    }
    if "landing_page" in opt:
        out["landing_page"] = opt["landing_page"]
    out["cancellation_policy"] = {}
    out["option_categories"] = copy.deepcopy(opt.get("option_categories") or [])
    rls = opt.get("related_locations") or []
    out["related_locations"] = [normalize_related_location(copy.deepcopy(rl)) for rl in rls]
    out["price_options"] = copy.deepcopy(opt.get("price_options") or [])
    return out


def normalize_product_klcc(product: dict) -> dict:
    p = copy.deepcopy(product)
    if p.get("id") == "Product-5":
        p["id"] = "product-5"

    extra_features: list = []
    raw_options = p.get("options") or []
    for opt in raw_options:
        extra_features.extend(collect_option_extras_for_features(opt))

    features = copy.deepcopy(p.get("product_features") or [])
    features.extend(extra_features)

    place_hint = first_place_id_in_options(raw_options)
    op = normalize_operator(p, place_hint)

    out: dict = {
        "id": p["id"],
        "title": p["title"],
        "description": p["description"],
    }
    if "rating" in p:
        out["rating"] = p["rating"]
    out["product_features"] = features
    out["options"] = [normalize_option(opt) for opt in raw_options]
    if "related_media" in p:
        out["related_media"] = copy.deepcopy(p["related_media"])
    if "inventory_types" in p:
        out["inventory_types"] = copy.deepcopy(p["inventory_types"])
    if op is not None:
        out["operator"] = op
    return reorder_product_klcc(out)


def reorder_product_klcc(p: dict) -> dict:
    """Match TTDKLCC.json top-level key order; unknown keys preserved at end."""
    order = (
        "id",
        "title",
        "description",
        "rating",
        "product_features",
        "options",
        "related_media",
        "inventory_types",
        "operator",
    )
    out = {}
    for k in order:
        if k in p:
            out[k] = p[k]
    for k, v in p.items():
        if k not in out:
            out[k] = v
    return out


def strip_lat_long(obj):
    """Remove coordinates / latitude / longitude from nested feed JSON."""
    if isinstance(obj, dict):
        return {
            k: strip_lat_long(v)
            for k, v in obj.items()
            if k not in ("coordinates", "latitude", "longitude")
        }
    if isinstance(obj, list):
        return [strip_lat_long(x) for x in obj]
    return obj


def main() -> None:
    all_products = []
    max_nonce = 0

    for name in FILES:
        path = BASE / name
        if not path.exists():
            raise FileNotFoundError(path)
        data = json.load(path.open(encoding="utf-8"))
        meta = data["feed_metadata"]
        n = meta.get("nonce", 0)
        if isinstance(n, int) and n > max_nonce:
            max_nonce = n

        for prod in data["products"]:
            all_products.append(normalize_product_klcc(prod))

    ids = [p["id"] for p in all_products]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise SystemExit(f"Duplicate product ids after merge: {dupes}")

    merged = {
        "feed_metadata": {
            "shard_id": 0,
            "total_shards_count": 1,
            "processing_instruction": "PROCESS_AS_SNAPSHOT",
            "nonce": max_nonce + 1,
        },
        "products": all_products,
    }
    merged = strip_lat_long(merged)
    OUT.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUT} with {len(all_products)} products, nonce {merged['feed_metadata']['nonce']}")


if __name__ == "__main__":
    main()
