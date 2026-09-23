"""Media filename similarity and clash detection logic."""

import difflib
from pathlib import Path
import re
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from config.paths import get_asset_dir, get_subcategory_dir
from database.collections import ASSETS, CATEGORIES, SUBCATEGORIES
from utils.file_utils import sanitize_filename
from utils.ids import to_object_id
from utils.slugify import slugify


def normalize_stem(name: str) -> str:
    """Normalize a filename or asset name for similarity comparison.

    Strips extensions, lowercases, replaces non-alphanumeric characters with spaces,
    and strips extra whitespace.
    """
    stem = Path(name).stem if "." in name else name
    cleaned = re.sub(r"[\W_]+", " ", stem).strip().lower()
    return cleaned


def calculate_similarity(name_a: str, name_b: str) -> float:
    """Calculate similarity ratio between two names."""
    norm_a = normalize_stem(name_a)
    norm_b = normalize_stem(name_b)
    if not norm_a or not norm_b:
        return 0.0
    if norm_a == norm_b:
        return 1.0
    return difflib.SequenceMatcher(None, norm_a, norm_b).ratio()


def suggest_next_filename(original_filename: str, taken_filenames: set[str]) -> str:
    """Generate a clean, non-conflicting filename by appending an incremental counter."""
    path = Path(original_filename)
    stem = path.stem
    ext = path.suffix

    # Strip existing trailing counter like _1, -1, _2, or 1
    counter_pattern = re.compile(r"^(.*?)([-_ ]?)(\d+)$")
    match = counter_pattern.match(stem)
    if match:
        base_stem = match.group(1)
        sep = match.group(2) or "_"
        start_counter = int(match.group(3)) + 1
    else:
        base_stem = stem
        sep = "_"
        start_counter = 1

    taken_lower = {t.lower() for t in taken_filenames} | {
        normalize_stem(t) for t in taken_filenames
    }

    counter = start_counter
    while True:
        candidate = f"{base_stem}{sep}{counter}{ext}"
        candidate_norm = normalize_stem(candidate)
        # Check if candidate or candidate_norm exists in taken_filenames (case-insensitive)
        if candidate.lower() not in taken_lower and candidate_norm not in taken_lower:
            return candidate
        counter += 1


async def check_filename_similarity(
    db: AsyncIOMotorDatabase,
    filenames: list[str],
    category_id: str | None = None,
    sub_category_id: str | None = None,
    existing_staged: list[str] | None = None,
    asset_id: str | None = None,
    asset_folder: str | None = None,
    asset_name: str | None = None,
) -> list[dict[str, Any]]:
    """Inspect disk and database to detect exact or similar filenames.

    Returns a list of conflict analysis results for each provided filename.
    """
    if not filenames:
        return []

    # Resolve target asset folder if asset context is provided
    clean_asset_folder: str | None = asset_folder.strip("/\\ ") if asset_folder and asset_folder.strip("/\\ ") else None
    if not clean_asset_folder and asset_id:
        try:
            asset_doc = await db[ASSETS].find_one(
                {"_id": to_object_id(asset_id), "deleted_at": None}
            )
            if asset_doc:
                clean_asset_folder = asset_doc.get("folder_name") or slugify(asset_doc.get("name", ""))
        except Exception:
            pass
    if not clean_asset_folder and asset_name and asset_name.strip():
        clean_asset_folder = slugify(asset_name.strip())

    # 1. Resolve target folder on disk and existing disk files
    existing_disk_files: list[str] = []
    if category_id and sub_category_id:
        try:
            cat_doc = await db[CATEGORIES].find_one(
                {"_id": to_object_id(category_id), "deleted_at": None}
            )
            sub_doc = await db[SUBCATEGORIES].find_one(
                {"_id": to_object_id(sub_category_id), "deleted_at": None}
            )
            if cat_doc and sub_doc:
                cat_folder = cat_doc.get("folder_name") or slugify(cat_doc.get("name", ""))
                sub_folder = sub_doc.get("folder_name") or slugify(sub_doc.get("name", ""))
                if clean_asset_folder:
                    dest_dir = get_asset_dir(cat_folder, sub_folder, clean_asset_folder)
                else:
                    dest_dir = get_subcategory_dir(cat_folder, sub_folder)
                if dest_dir.exists() and dest_dir.is_dir():
                    existing_disk_files = [
                        f.name for f in dest_dir.iterdir() if f.is_file() and not f.name.startswith(".")
                    ]
        except Exception:
            pass

    # 2. Resolve existing assets in MongoDB for the target subcategory
    # ONLY check candidate filenames against other asset titles if NOT scoped to a specific asset.
    # When uploading media inside an asset folder, files are scoped to that asset.
    existing_asset_names: list[str] = []
    if sub_category_id and not clean_asset_folder and not asset_id:
        try:
            sub_oid = to_object_id(sub_category_id)
            cursor = db[ASSETS].find(
                {"sub_category_id": sub_oid, "deleted_at": None},
                {"name": 1, "thumbnail_url": 1},
            )
            async for doc in cursor:
                if doc.get("name"):
                    existing_asset_names.append(doc["name"])
        except Exception:
            pass

    # Build set of all taken names (lowercased and normalized), including any already-staged files
    staged_list = existing_staged or []
    all_taken_raw: set[str] = (
        {f.lower() for f in existing_disk_files}
        | {a.lower() for a in existing_asset_names}
        | {s.lower() for s in staged_list}
    )
    all_taken_norms: set[str] = (
        {normalize_stem(f) for f in existing_disk_files}
        | {normalize_stem(a) for a in existing_asset_names}
        | {normalize_stem(s) for s in staged_list}
    )
    all_taken = all_taken_raw | all_taken_norms

    results: list[dict[str, Any]] = []

    # Also keep track of filenames within this batch to avoid internal duplicates
    batch_taken: set[str] = set()

    for raw_filename in filenames:
        safe_name = sanitize_filename(raw_filename)
        norm_name = normalize_stem(safe_name)

        has_conflict = False
        conflict_type = None
        matched_name = None
        highest_similarity = 0.0

        # Check against existing disk files (exact match: same filename)
        for existing in existing_disk_files:
            if existing.lower() == safe_name.lower():
                has_conflict = True
                conflict_type = "exact"
                matched_name = existing
                highest_similarity = 1.0
                break

            ratio = calculate_similarity(safe_name, existing)
            if ratio > highest_similarity:
                highest_similarity = ratio

        # Check against existing asset names in DB (exact collision if normalized stems match)
        if not has_conflict:
            for asset_name in existing_asset_names:
                if (
                    normalize_stem(asset_name) == norm_name
                    or asset_name.strip().lower() == safe_name.lower()
                ):
                    has_conflict = True
                    conflict_type = "exact"
                    matched_name = asset_name
                    highest_similarity = 1.0
                    break

                ratio = calculate_similarity(safe_name, asset_name)
                if ratio > highest_similarity:
                    highest_similarity = ratio

        # Check against already-staged files passed from the client
        if not has_conflict:
            for s in staged_list:
                if s.lower() == safe_name.lower() or normalize_stem(s) == norm_name:
                    has_conflict = True
                    conflict_type = "exact"
                    matched_name = s
                    highest_similarity = 1.0
                    break

        # Check against other files in the same batch (exact collision or identical normalized stem)
        if not has_conflict:
            for b in batch_taken:
                if b.lower() == safe_name.lower() or normalize_stem(b) == norm_name:
                    has_conflict = True
                    conflict_type = "exact"
                    matched_name = b
                    highest_similarity = 1.0
                    break

        batch_taken.add(safe_name)
        batch_taken.add(safe_name.lower())
        batch_taken.add(norm_name)

        suggested_name = None
        if has_conflict:
            suggested_name = suggest_next_filename(safe_name, all_taken | batch_taken)
            batch_taken.add(suggested_name)
            batch_taken.add(suggested_name.lower())
            batch_taken.add(normalize_stem(suggested_name))

        results.append(
            {
                "filename": raw_filename,
                "safe_filename": safe_name,
                "has_conflict": has_conflict,
                "conflict_type": conflict_type,
                "matched_name": matched_name,
                "similarity": round(highest_similarity, 2),
                "suggested_filename": suggested_name,
            }
        )

    return results
