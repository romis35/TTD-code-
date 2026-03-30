"""Merge all ttd_from_cms/TTD_*.json single-product feeds into one JSON file."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import _merge_ttd as m

BASE = Path(__file__).resolve().parent
CMS_DIR = BASE / "ttd_from_cms"
OUT = BASE / "TTD_FROM_CMS_ALL.json"

# When CMS JSON has no rating, use these so every merged product includes rating_count.
# Replace with real Google Business Profile figures when available.
DEFAULT_RATING_AVG = 4.3
DEFAULT_RATING_COUNT = 100


def _ensure_rating(product: dict) -> dict:
    """Guarantee rating.average_value and rating.rating_count on every product."""
    out = copy.deepcopy(product)
    r = out.get("rating")
    if not isinstance(r, dict):
        r = {}
    avg = r.get("average_value")
    cnt = r.get("rating_count")
    try:
        avg_f = float(avg) if avg is not None else None
    except (TypeError, ValueError):
        avg_f = None
    try:
        cnt_i = int(cnt) if cnt is not None else None
    except (TypeError, ValueError):
        cnt_i = None
    if avg_f is None:
        avg_f = float(DEFAULT_RATING_AVG)
    if cnt_i is None:
        cnt_i = int(DEFAULT_RATING_COUNT)
    out["rating"] = {"average_value": avg_f, "rating_count": cnt_i}
    return m.reorder_product_klcc(out)


def _product_title_key(product: dict) -> str:
    texts = (product.get("title") or {}).get("localized_texts") or []
    for t in texts:
        if (t.get("language_code") or "").lower().startswith("en"):
            return (t.get("text") or "").strip()
    if texts:
        return (texts[0].get("text") or "").strip()
    return ""


def _load_reference_by_title() -> dict[str, dict]:
    """Hand-crafted TTD*.json products keyed by English title (TTDKLCC-style source)."""
    ref: dict[str, dict] = {}
    for name in m.FILES:
        path = BASE / name
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for prod in data.get("products") or []:
            k = _product_title_key(prod)
            if k:
                ref[k] = prod
    return ref


def _enrich_from_handcrafted(product: dict, ref_by_title: dict[str, dict]) -> dict:
    """Fill rating / related_media from reference when title matches (e.g. TTDKLCC Aquaria)."""
    key = _product_title_key(product)
    raw = ref_by_title.get(key)
    if not raw:
        return product
    ref_norm = m.normalize_product_klcc(copy.deepcopy(raw))
    out = copy.deepcopy(product)
    if "rating" not in out and ref_norm.get("rating"):
        out["rating"] = copy.deepcopy(ref_norm["rating"])
    cms_rm = out.get("related_media") or []
    ref_rm = ref_norm.get("related_media") or []

    def has_wikimedia(items: list) -> bool:
        for x in items:
            u = (x.get("url") or "").lower()
            if "wikimedia" in u:
                return True
        return False

    if ref_rm and (has_wikimedia(ref_rm) or len(ref_rm) > len(cms_rm)):
        out["related_media"] = copy.deepcopy(ref_rm)
    return m.reorder_product_klcc(out)


def file_sort_key(path: Path) -> tuple[int, str]:
    stem = path.stem
    mnum = re.match(r"TTD_(\d+)$", stem)
    if mnum:
        return (int(mnum.group(1)), stem)
    return (10**12, stem)


def main() -> None:
    if not CMS_DIR.is_dir():
        raise SystemExit(f"Missing directory {CMS_DIR}")

    paths = sorted(CMS_DIR.glob("TTD_*.json"), key=file_sort_key)
    if not paths:
        raise SystemExit(f"No TTD_*.json files in {CMS_DIR}")

    all_products: list = []
    max_nonce = 0
    ref_by_title = _load_reference_by_title()

    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        meta = data.get("feed_metadata") or {}
        n = meta.get("nonce", 0)
        if isinstance(n, int) and n > max_nonce:
            max_nonce = n
        for prod in data.get("products") or []:
            norm = m.normalize_product_klcc(copy.deepcopy(prod))
            step = _enrich_from_handcrafted(norm, ref_by_title)
            all_products.append(_ensure_rating(step))

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
    merged = m.strip_lat_long(merged)
    OUT.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {OUT} with {len(all_products)} products from {len(paths)} files, "
        f"nonce {merged['feed_metadata']['nonce']}"
    )


if __name__ == "__main__":
    main()
