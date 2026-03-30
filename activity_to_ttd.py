"""
Convert activity_data.json (CMS export) into one Things-to-Do JSON file per activity,
using TTDKLCC.json as the structural reference (feed_metadata + single product shape).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

BASE = Path(__file__).resolve().parent
ACTIVITY_JSON = BASE / "activity_data.json"
OUT_DIR = BASE / "ttd_from_cms"

# Placeholder until real Google Business Profile ratings exist; keep in sync with merge_ttd_from_cms.DEFAULT_RATING_*.
DEFAULT_RATING_AVG = 4.3
DEFAULT_RATING_COUNT = 100


def slugify(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "activity"


def localized(text: str) -> dict:
    return {
        "localized_texts": [
            {"language_code": "en", "text": (text or "").strip()},
        ]
    }


def type_slug(name: str) -> str:
    n = (name or "").strip().lower()
    mapping = {
        "adult": "adult",
        "child": "child",
        "senior": "senior",
        "infant": "infant",
        "student": "student",
    }
    if n in mapping:
        return mapping[n]
    return slugify(name)


def price_option_title(tt: dict) -> str:
    name = (tt.get("name") or "Guest").strip()
    af = tt.get("ageFrom")
    at = tt.get("ageTo")
    if af is not None and at is not None:
        return f"{name} ({af}–{at} yrs)"
    return name


def category_labels(overview: dict) -> List[Dict[str, str]]:
    labels: List[str] = []
    for cv in overview.get("categoryV3") or []:
        for ch in cv.get("children") or []:
            nm = ch.get("name")
            if nm:
                labels.append(slugify(nm))
    # de-dupe preserve order
    seen: Set[str] = set()
    out: List[Dict[str, str]] = []
    for lb in labels:
        if lb and lb not in seen:
            seen.add(lb)
            out.append({"label": lb})
    if not out:
        out.append({"label": "attraction-tickets"})
    return out


def venue_place_info(overview: dict) -> dict:
    v = overview.get("venue") or {}
    merchant = (overview.get("merchant") or {}).get("name") or overview.get("name") or ""
    addr = v.get("location") or ""
    pi: dict = {}
    if merchant:
        pi["name"] = str(merchant).strip()
    if addr:
        pi["unstructured_address"] = str(addr).strip()
    return pi


def related_location_from_venue(overview: dict) -> List[dict]:
    pi = venue_place_info(overview)
    if not pi:
        return []
    return [
        {
            "location": {"location": {"place_info": pi}},
            "relation_type": "RELATION_TYPE_ADMISSION_TICKET",
        }
    ]


def operator_block(overview: dict) -> dict:
    merchant = overview.get("merchant") or {}
    name = (merchant.get("name") or overview.get("name") or "").strip()
    out: dict = {
        "google_business_profile_name": localized(name),
    }
    locs: list[dict] = []
    pi = venue_place_info(overview)
    if pi:
        locs.append({"location": {"place_info": pi}})
    if locs:
        out["locations"] = locs
    return out


def landing_page_url(activity_id: str, overview: dict) -> str:
    city = slugify(overview.get("cityName") or "")
    if not city:
        city = slugify(overview.get("country") or "malaysia")
    path = slugify(overview.get("name") or "activity")
    return f"https://www.redbus.my/things-to-do/malaysia/{city}/{path}"


def related_media_for_activity(activity_id: str, overview: dict) -> List[dict]:
    imgs = overview.get("image") or []
    name = overview.get("name") or "Activity"
    media: list[dict] = []
    for stem in imgs:
        stem = str(stem).strip()
        if not stem:
            continue
        url = f"https://s3.rdbuz.com/activity-images/Activity/{activity_id}/DSP/{stem}.png"
        media.append(
            {
                "url": url,
                "type": "MEDIA_TYPE_PHOTO",
                "attribution": localized(name),
            }
        )
    return media


def info_view_to_features(info_view: Optional[Dict[str, Any]]) -> List[dict]:
    if not info_view:
        return []
    features: list[dict] = []
    for block in info_view.get("infoDetails") or []:
        title = (block.get("title") or "").strip()
        data_list = [
            str(x).strip()
            for x in (block.get("dataList") or [])
            if x is not None and str(x).strip()
        ]
        if title == "Highlights":
            ft = "TEXT_FEATURE_HIGHLIGHT"
        elif title in ("What to expect", "What's included", "What\u2019s included"):
            ft = "TEXT_FEATURE_INCLUSION"
        elif title == "Things to note":
            ft = "TEXT_FEATURE_MUST_KNOW"
        else:
            ft = "TEXT_FEATURE_MUST_KNOW"
        for text in data_list:
            features.append({"feature_type": ft, "value": localized(text)})
    return features


def ticket_meta_features(tickets: List[dict]) -> List[dict]:
    """Unique How to use / Terms / Cancellation lines from all ticket variants."""
    seen: set[str] = set()
    out: List[dict] = []
    for t in tickets:
        details = (t.get("ticketsViewDetails") or {}).get("details") or []
        for d in details:
            title = (d.get("title") or "").strip()
            if title == "Highlights":
                continue
            if title not in (
                "How to use",
                "Terms & Conditions",
                "Cancellation Policy",
                "What's included",
                "What\u2019s included",
            ):
                continue
            for line in d.get("dataList") or []:
                line = str(line).strip()
                if not line or line in seen:
                    continue
                seen.add(line)
                prefix = f"{title}: " if title else ""
                ft = (
                    "TEXT_FEATURE_INCLUSION"
                    if title in ("What's included", "What\u2019s included")
                    else "TEXT_FEATURE_MUST_KNOW"
                )
                out.append({"feature_type": ft, "value": localized(prefix + line)})
    return out


def build_options(activity_id: str, overview: dict, tickets: List[dict]) -> List[dict]:
    rloc = related_location_from_venue(overview)
    labels = category_labels(overview)
    url = landing_page_url(activity_id, overview)
    sorted_tickets = sorted(
        tickets,
        key=lambda x: (x.get("sortOrder") is None, x.get("sortOrder") or 999),
    )
    options: List[dict] = []
    for i, t in enumerate(sorted_tickets, start=1):
        ttypes = t.get("ticketType") or []
        price_options: list[dict] = []
        for tt in ttypes:
            nett = tt.get("nettPrice")
            if nett is None:
                continue
            try:
                units = int(round(float(nett)))
            except (TypeError, ValueError):
                continue
            cur = (tt.get("currency") or tt.get("purchaseCurrency") or "MYR").upper()
            suffix = type_slug(tt.get("name") or "guest")
            price_options.append(
                {
                    "id": f"option-{i}-{suffix}",
                    "title": price_option_title(tt),
                    "price": {"currency_code": cur, "units": units},
                }
            )
        options.append(
            {
                "id": f"option-{i}",
                "title": localized(t.get("name") or f"Option {i}"),
                "landing_page": {"url": url},
                "cancellation_policy": {},
                "option_categories": list(labels),
                "related_locations": list(rloc),
                "price_options": price_options,
            }
        )
    return options


def activity_to_feed(activity_id: str, payload: dict) -> dict:
    overview = payload.get("Overview") or {}
    tickets = payload.get("tickets") or []
    info_view = payload.get("infoViewDetails")

    name = (overview.get("name") or f"Activity {activity_id}").strip()
    desc = (overview.get("description") or "").strip()

    features = info_view_to_features(info_view)
    features.extend(ticket_meta_features(tickets))

    options = build_options(activity_id, overview, tickets)
    if not options:
        raise ValueError("no ticket options")

    product: dict = {
        "id": f"product-{activity_id}",
        "title": localized(name),
        "description": localized(desc),
        "rating": {
            "average_value": DEFAULT_RATING_AVG,
            "rating_count": DEFAULT_RATING_COUNT,
        },
        "product_features": features,
        "options": options,
    }

    media = related_media_for_activity(activity_id, overview)
    if media:
        product["related_media"] = media

    product["inventory_types"] = ["INVENTORY_TYPE_OPERATOR_DIRECT"]
    product["operator"] = operator_block(overview)

    try:
        from apply_place_ids import (
            MAP_FILE,
            apply_place_id_to_product,
            load_overrides,
            load_place_map,
            resolve_with_overrides,
        )

        if MAP_FILE.exists():
            _pm = load_place_map()
            _ov = load_overrides()
            _pid = resolve_with_overrides(name, f"product-{activity_id}", _pm, _ov)
            if _pid:
                apply_place_id_to_product(product, _pid)
    except Exception:
        pass

    try:
        aid_num = int(activity_id)
    except ValueError:
        aid_num = abs(hash(activity_id)) % 10000
    nonce = int(datetime.now(timezone.utc).strftime("%Y%m%d%H%M")) + (aid_num % 100)

    return {
        "feed_metadata": {
            "shard_id": 0,
            "total_shards_count": 1,
            "processing_instruction": "PROCESS_AS_SNAPSHOT",
            "nonce": nonce,
        },
        "products": [product],
    }


def main() -> None:
    if not ACTIVITY_JSON.exists():
        raise SystemExit(f"Missing {ACTIVITY_JSON}")

    data = json.loads(ACTIVITY_JSON.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    ok = 0
    err: list[tuple[str, str]] = []
    for aid, payload in data.items():
        if not isinstance(payload, dict):
            continue
        try:
            feed = activity_to_feed(str(aid), payload)
        except Exception as e:
            err.append((str(aid), str(e)))
            continue
        out_path = OUT_DIR / f"TTD_{aid}.json"
        out_path.write_text(
            json.dumps(feed, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        ok += 1

    print(f"Wrote {ok} files to {OUT_DIR}")
    if err:
        print(f"Skipped {len(err)} activities:")
        for aid, msg in err[:20]:
            print(f"  {aid}: {msg}")
        if len(err) > 20:
            print(f"  ... and {len(err) - 20} more")


if __name__ == "__main__":
    main()
