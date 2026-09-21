from __future__ import annotations

import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VIEWER_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "data" / "outputs"
VERSIONS_TARGET = VIEWER_ROOT / "public" / "bencao-versions"
LEGACY_TARGET = VIEWER_ROOT / "public" / "bencao-output"

VERSION_DEFS = [
    {
        "id": "pages_001_020_final",
        "label": "旧版 final",
        "description": "上一轮前20页结果，用于对比",
    },
    {
        "id": "pages_001_020_layout_v2",
        "label": "新版 layout_v2",
        "description": "双层框：文字框 text_box + 栏位框 layout_box",
    },
]

JSON_FILES = [
    "pages.json",
    "regions.json",
    "final_records.json",
    "page_quality_report.json",
    "ocr_candidates.json",
]


def copy_tree_contents(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            copy_tree_contents(item, target)
        else:
            shutil.copy2(item, target)


def copy_version(version_id: str) -> bool:
    src_root = OUTPUT_ROOT / version_id
    if not src_root.exists():
        print(f"Skip missing version: {src_root}")
        return False

    dst_root = VERSIONS_TARGET / version_id
    dst_root.mkdir(parents=True, exist_ok=True)
    for name in JSON_FILES:
        src = src_root / name
        if not src.exists():
            raise SystemExit(f"Missing required file: {src}")
        shutil.copy2(src, dst_root / name)

    copy_tree_contents(src_root / "preprocessed_pages", dst_root / "preprocessed_pages")
    copy_tree_contents(src_root / "annotated_pages", dst_root / "annotated_pages")
    print(f"Prepared version: {version_id}")
    return True


def main() -> None:
    VERSIONS_TARGET.mkdir(parents=True, exist_ok=True)
    prepared = []
    for item in VERSION_DEFS:
        if copy_version(item["id"]):
            prepared.append({**item, "path": item["id"]})

    if not prepared:
        raise SystemExit("No output versions were prepared.")

    default_id = "pages_001_020_layout_v2" if any(v["id"] == "pages_001_020_layout_v2" for v in prepared) else prepared[0]["id"]
    manifest = {
        "defaultVersion": default_id,
        "versions": prepared,
    }
    (VERSIONS_TARGET / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # Keep the old /bencao-output path usable for older builds.
    legacy_src = OUTPUT_ROOT / default_id
    if legacy_src.exists():
        LEGACY_TARGET.mkdir(parents=True, exist_ok=True)
        for name in JSON_FILES:
            shutil.copy2(legacy_src / name, LEGACY_TARGET / name)
        copy_tree_contents(legacy_src / "preprocessed_pages", LEGACY_TARGET / "preprocessed_pages")
        copy_tree_contents(legacy_src / "annotated_pages", LEGACY_TARGET / "annotated_pages")

    print(f"Prepared viewer manifest: {VERSIONS_TARGET / 'manifest.json'}")


if __name__ == "__main__":
    main()
