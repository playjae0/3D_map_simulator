"""2단계 정제: GIS건물통합정보(AL_D010) SHP → 처리 결과 스키마(docs/schema.md) GeoParquet.

사용 예:
    python scripts/refine.py data/raw/AL_D010_36_20261109.zip
    → data/processed/buildings_36.parquet, data/processed/buildings_36.meta.json

규칙은 docs/data.md "높이 정제 규칙"(임시 확정). 아래 상수는 세종 값이며 서울 확인 후 확정한다.
원본 A16·A26은 src_height·src_floors로 그대로 보존한다.
"""
import argparse
import csv
import json
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

# ---- 규칙 매개변수 (임시, 세종 1단계 결과) ----
PLACEHOLDER_AREA = 1.0                 # m², 미만이면 placeholder로 제외
H_MIN, H_MAX = 2.0, 600.0              # 절대 범위(안전장치)
RATIO_MIN, RATIO_MAX = 2.0, 8.0        # 2층 이상 높이/층수 정상 범위
SINGLE_MAX = 20.0                      # 1층 높이 상한
# 1층·20m 초과 검사 대상 용도. 그 밖의 용도(공장·굴뚝이 있는 처리시설 등)와 주용도 결측은 원본 유지
SINGLE_CHECK = {"단독주택", "공동주택", "제1종근린생활시설", "제2종근린생활시설", "근린생활시설", "업무시설"}
FLOOR_A, FLOOR_B = 1.9, 2.9            # 층수 대체: a + b×층수
AREA_BINS = [0, 20, 50, 100, 200, 500, np.inf]
AREA_DEFAULT = [3.5, 4.0, 4.7, 5.9, 7.5, 9.5]
LARGE_DEFAULT_AREA = 300.0

# AL_D010 칼럼 → 의미
COL = {"id": "A0", "sigungu": "A23", "use": "A9", "approval": "A13", "height": "A16", "floors": "A26"}

FACADE_CSV = Path(__file__).with_name("facade_groups.csv")


def norm_use(s: pd.Series) -> pd.Series:
    return s.astype("string").str.replace(r"[\s.·ㆍ]", "", regex=True)


def load_facade_map() -> dict:
    with open(FACADE_CSV, encoding="utf-8") as f:
        return {re.sub(r"[\s.·ㆍ]", "", r["use_name"]): r["facade"] for r in csv.DictReader(f)}


def refine(g: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, dict]:
    n = len(g)
    flags = [[] for _ in range(n)]

    def add(mask, flag):
        for i in np.flatnonzero(np.asarray(mask)):
            flags[i].append(flag)

    geom = np.asarray(g.geometry.values)
    invalid = ~shapely.is_valid(geom) & ~shapely.is_empty(geom)
    if invalid.any():
        fixed = shapely.make_valid(geom[invalid])
        # 면 부분만 남긴다
        fixed = np.array([shapely.union_all([p for p in shapely.get_parts(x) if p.geom_type in ("Polygon", "MultiPolygon")]) for x in fixed])
        geom[invalid] = fixed
        add(invalid, "geom_fixed")
    area = shapely.area(geom)

    src_h = g[COL["height"]].astype("float64")
    src_fl = g[COL["floors"]].astype("float64")
    h = src_h.fillna(0).to_numpy()
    fl = src_fl.fillna(0).to_numpy()
    use = g[COL["use"]].astype("string")
    use_n = norm_use(use)

    # 0. 형상 제외
    placeholder = area < PLACEHOLDER_AREA
    add(placeholder, "no_footprint")
    wkb = pd.Series(shapely.to_wkb(shapely.normalize(shapely.set_precision(geom, 0.001))))
    order = np.argsort(g[COL["id"]].to_numpy(), kind="stable")          # 같은 형상이면 id가 작은 쪽을 남긴다
    dup = np.zeros(n, bool)
    dup[order] = wkb.iloc[order].duplicated(keep="first").to_numpy()
    dup &= ~placeholder
    add(dup, "duplicate")
    excluded = placeholder | dup

    # 1. 원본 높이 판정
    has_h = h > 0
    out_rng = has_h & ((h < H_MIN) | (h > H_MAX))
    ratio = np.divide(h, fl, out=np.zeros(n), where=fl > 0)
    multi = has_h & ~out_rng & (fl >= 2)
    r_low = multi & (ratio < RATIO_MIN)
    r_high = multi & (ratio > RATIO_MAX)
    single_tall = has_h & ~out_rng & (fl == 1) & (h > SINGLE_MAX)
    checked = use_n.isin({re.sub(r"[\s.·ㆍ]", "", u) for u in SINGLE_CHECK}).fillna(False).to_numpy()
    exempt = single_tall & ~checked
    keep = ~excluded                                                      # 높이 플래그는 렌더링 대상에만 붙인다
    add(out_rng & keep, "out_of_range")
    add(r_low & keep, "ratio_low")
    add(r_high & keep, "ratio_high")
    add(single_tall & ~exempt & keep, "single_story_tall")
    add(exempt & keep, "single_story_tall_kept")
    orig_ok = has_h & ~out_rng & ~r_low & ~r_high & ~(single_tall & ~exempt)

    # 2. 층수 대체, 3. 면적 기본값
    use_floors = ~orig_ok & (fl > 0)
    use_area = ~orig_ok & ~use_floors
    area_h = np.asarray(AREA_DEFAULT)[np.digitize(area, AREA_BINS[1:-1])]
    add(use_area & ~excluded & (area >= LARGE_DEFAULT_AREA), "large_default")

    height = np.where(orig_ok, h, np.where(use_floors, FLOOR_A + FLOOR_B * fl, area_h)).astype("float32")
    h_src = np.where(orig_ok, "orig", np.where(use_floors, "floors", "area_default")).astype(object)
    h_src[excluded] = "excluded"
    height_out = pd.array(height, dtype="Float32")
    height_out[excluded] = pd.NA

    fmap = load_facade_map()
    facade = use_n.map(fmap).fillna("unknown")
    unmapped = sorted(set(use.dropna()[facade[use.notna()] == "unknown"]))

    yr = pd.to_datetime(g[COL["approval"]], errors="coerce").dt.year.astype("Int16")

    out = gpd.GeoDataFrame({
        "bldg_id": g[COL["sigungu"]].astype(str) + "-" + g[COL["id"]].astype(str),
        "height_m": height_out,
        "h_src": pd.Series(h_src, dtype="string"),
        "h_flag": pd.Series(["|".join(f) for f in flags], dtype="string"),
        "facade": facade.astype("string"),
        "approval_year": yr,
        "src_height": src_h.astype("Float32"),
        "src_floors": src_fl.astype("Int16"),
    }, geometry=gpd.GeoSeries(geom, crs=g.crs), crs=g.crs)
    assert out.bldg_id.is_unique

    flag_counts = pd.Series([f for fs in flags for f in fs]).value_counts().to_dict()
    meta = {
        "rules": {"placeholder_area_m2": PLACEHOLDER_AREA, "abs_range_m": [H_MIN, H_MAX],
                  "ratio_range_multi_story": [RATIO_MIN, RATIO_MAX], "single_story_max_m": SINGLE_MAX,
                  "single_story_check_uses": sorted(SINGLE_CHECK), "floors_formula": f"{FLOOR_A} + {FLOOR_B} * floors",
                  "area_default": {f"[{a},{b})": v for a, b, v in zip(AREA_BINS[:-1], AREA_BINS[1:], AREA_DEFAULT)},
                  "large_default_area_m2": LARGE_DEFAULT_AREA, "status": "임시. 서울 확인 후 확정"},
        "counts": {
            "total": n,
            "h_src": out.h_src.value_counts().to_dict(),
            "h_flag": {k: int(v) for k, v in flag_counts.items()},
            "facade": out.facade.value_counts().to_dict(),
            "facade_rendered": out.facade[~excluded].value_counts().to_dict(),
            "h_src_by_facade": pd.crosstab(out.facade, out.h_src).to_dict("index"),
        },
        "unmapped_use_names": unmapped,
        "height_rendered_pct": {f"p{q}": round(float(np.percentile(height[~excluded], q)), 2) for q in (5, 25, 50, 75, 95, 99, 100)},
    }
    return out, meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--encoding", default="cp949")
    ap.add_argument("--out", default=None, help="기본: data/processed/buildings_<지역>.parquet")
    a = ap.parse_args()

    region = re.search(r"AL_D010_(\d+)", Path(a.path).name)
    region = region.group(1) if region else Path(a.path).stem
    out_path = Path(a.out or f"data/processed/buildings_{region}.parquet")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    g = gpd.read_file(a.path, encoding=a.encoding)
    if g.crs is None:
        raise SystemExit("CRS가 없습니다. .prj 파일을 확인하세요.")
    g = g.to_crs(5186)
    out, meta = refine(g)
    meta = {"source": Path(a.path).name, "region": region, "crs": "EPSG:5186", **meta}
    out.to_parquet(out_path, index=False)
    with open(out_path.with_suffix(".meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1, default=int)
    print(json.dumps(meta["counts"], ensure_ascii=False, indent=1, default=int))
    print("unmapped:", meta["unmapped_use_names"])
    print("saved:", out_path)


if __name__ == "__main__":
    main()
