"""3단계 타일·LOD: 처리 결과(docs/schema.md) → 500m 타일별 바이너리 + manifest.json.

사용 예:
    python scripts/tile.py data/processed/buildings_36.parquet
    → data/processed/tiles/36/manifest.json, data/processed/tiles/36/<lod>/<x>_<y>.bin

형식은 docs/tiles.md. 건물은 중심점이 속한 타일에 배정한다(자르지 않음).
LOD 0: 원래 외곽선 / LOD 1: 최소 회전 사각형(박스) / LOD 2: 작은 저층 건물 생략 + 박스
창 격자용 층수(u8)를 함께 저장한다(BLDT v2).
"""
import argparse
import gzip
import json
import struct
from datetime import date
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely

from overview import area_labels, render_overview

FACADE_ENUM = ["unknown", "apartment", "house", "commercial", "office", "industrial", "public"]
MAGIC, VERSION = b"BLDT", 2   # v2: 층수(u8) 배열 추가
MIN_FLOOR_SAMPLE = 100       # 그룹 층고 중앙값을 쓰는 최소 표본 수. 미만이면 전체 중앙값
LOD2_MIN_AREA, LOD2_MIN_HEIGHT = 100.0, 12.0   # LOD2는 면적 100m² 이상 또는 높이 12m 이상만 남긴다


def lod_geoms(b: gpd.GeoDataFrame, lod: int):
    geom = np.asarray(b.geometry.values)
    keep = np.ones(len(b), bool)
    if lod >= 1:
        geom = shapely.oriented_envelope(geom)
    if lod == 2:
        keep = (shapely.area(np.asarray(b.geometry.values)) >= LOD2_MIN_AREA) | (b.height_m.to_numpy(float) >= LOD2_MIN_HEIGHT)
    return geom, keep


def flatten(geom: np.ndarray):
    """건물 → 프리즘(폴리곤 파트) → 링 → 꼭짓점. 외곽 링 반시계, 구멍 시계, 닫는 점 제외."""
    geom = shapely.remove_repeated_points(geom, 0.01)
    parts, part_bldg = shapely.get_parts(geom, return_index=True)
    parts = shapely.orient_polygons(parts, exterior_cw=False)
    rings, ring_part = shapely.get_rings(parts, return_index=True)
    coords, coord_ring = shapely.get_coordinates(rings, return_index=True)
    last = np.r_[coord_ring[1:] != coord_ring[:-1], True]            # 각 링의 마지막(=첫 점 반복) 좌표
    coords, coord_ring = coords[~last], coord_ring[~last]
    nv = np.bincount(coord_ring, minlength=len(rings))
    if (nv < 3).any():
        raise ValueError(f"꼭짓점 3개 미만 링 {int((nv < 3).sum())}개")
    return part_bldg, ring_part, coords, coord_ring, nv


def tri_count(nv_rings: np.ndarray, ring_part: np.ndarray, n_parts: int) -> np.ndarray:
    e = np.bincount(ring_part, weights=nv_rings, minlength=n_parts)
    holes = np.bincount(ring_part, minlength=n_parts) - 1
    return (2 * e + (e - 2 + 2 * holes)).astype(np.int64)            # 벽 2e + 지붕 (e-2+2h), 바닥 없음


def floors_used(b) -> tuple[np.ndarray, dict]:
    """창 격자용 층수. 원본 층수가 높이 산정에 쓰였으면(orig·floors) 그 값, 아니면 높이 / 그룹 층고 중앙값."""
    fl = b.src_floors.fillna(0).to_numpy(float)
    h = b.height_m.to_numpy(float)
    known = b.h_src.isin(["orig", "floors"]).to_numpy() & (fl > 0)
    sample = known & (b.h_src == "orig").to_numpy()
    ratio = h[sample] / fl[sample]
    overall = float(np.median(ratio))
    fh = {}
    for gname in FACADE_ENUM:
        m = (b.facade.to_numpy()[sample] == gname)
        fh[gname] = round(float(np.median(ratio[m])), 2) if m.sum() >= MIN_FLOOR_SAMPLE else round(overall, 2)
    est = np.maximum(1, np.round(h / b.facade.map(fh).to_numpy(float)))
    out = np.where(known, fl, est)
    return np.clip(out, 1, 255).astype(np.uint8), {"floor_height_m": fh, "overall_m": round(overall, 2),
        "rule": "h_src가 orig·floors이고 원본 층수>0이면 원본 층수, 아니면 round(height_m / 그룹 층고 중앙값), 최소 1. "
                f"층고 중앙값은 h_src=orig·층수>0 표본, 그룹 표본 {MIN_FLOOR_SAMPLE}개 미만이면 전체 중앙값"}


def encode(ix, iy, lod, ring_part, nv, coords, height, facade, floors, origin) -> bytes:
    n_parts, n_rings, n_verts = len(height), len(nv), len(coords)
    prism_ring_start = np.r_[0, np.cumsum(np.bincount(ring_part, minlength=n_parts))].astype("<u4")
    ring_vert_start = np.r_[0, np.cumsum(nv)].astype("<u4")
    head = MAGIC + struct.pack("<BBHIIIIii", VERSION, lod, 0, n_parts, n_rings, n_verts, 0, ix, iy)
    assert len(head) == 32
    body = [prism_ring_start.tobytes(), ring_vert_start.tobytes(),
            (coords - origin).astype("<f4").tobytes(), height.astype("<f4").tobytes(), facade.astype("u1").tobytes(),
            floors.astype("u1").tobytes()]
    out = head + b"".join(body)
    return out + b"\0" * (-len(out) % 4)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--tile", type=int, default=500)
    ap.add_argument("--out", default=None, help="기본: data/processed/tiles/<지역>")
    a = ap.parse_args()

    meta_path = Path(a.path).with_suffix(".meta.json")
    region = json.load(open(meta_path, encoding="utf-8"))["region"] if meta_path.exists() else Path(a.path).stem
    out_dir = Path(a.out or f"data/processed/tiles/{region}")

    b = gpd.read_parquet(a.path)
    assert b.crs.to_epsg() == 5186, "EPSG:5186이어야 합니다"
    b = b[b.h_src != "excluded"].reset_index(drop=True)
    T = a.tile
    c = shapely.centroid(np.asarray(b.geometry.values))
    tx = np.floor(shapely.get_x(c) / T).astype(np.int64)
    ty = np.floor(shapely.get_y(c) / T).astype(np.int64)
    order = np.lexsort((ty, tx))
    b, tx, ty = b.iloc[order].reset_index(drop=True), tx[order], ty[order]
    fac = b.facade.map({k: i for i, k in enumerate(FACADE_ENUM)}).fillna(0).to_numpy(np.uint8)
    hgt = b.height_m.to_numpy(np.float32)
    flr, floor_info = floors_used(b)

    tiles = {}
    summary = {}
    for lod in (0, 1, 2):
        geom, keep = lod_geoms(b, lod)
        idx = np.flatnonzero(keep)
        part_bldg, ring_part, coords, coord_ring, nv = flatten(geom[idx])
        part_bldg = idx[part_bldg]
        n_parts = len(part_bldg)
        tri = tri_count(nv, ring_part, n_parts)
        pkey = tx[part_bldg] * 10_000_000 + ty[part_bldg]
        keys, p_start = np.unique(pkey, return_index=True)
        p_end = np.r_[p_start[1:], n_parts]
        r_start = np.searchsorted(ring_part, p_start)
        r_end = np.searchsorted(ring_part, p_end)
        c_start = np.searchsorted(coord_ring, r_start)
        c_end = np.searchsorted(coord_ring, r_end)
        (out_dir / str(lod)).mkdir(parents=True, exist_ok=True)
        tot_raw = tot_gz = 0
        sizes = []
        for k, p0, p1, r0, r1, c0, c1 in zip(keys, p_start, p_end, r_start, r_end, c_start, c_end):
            ix, iy = int(k // 10_000_000), int(k % 10_000_000)
            origin = np.array([ix * T, iy * T], float)
            data = encode(ix, iy, lod, ring_part[r0:r1] - p0, nv[r0:r1], coords[c0:c1], hgt[part_bldg[p0:p1]], fac[part_bldg[p0:p1]], flr[part_bldg[p0:p1]], origin)
            (out_dir / str(lod) / f"{ix}_{iy}.bin").write_bytes(data)
            gz = len(gzip.compress(data, 6))
            tot_raw += len(data)
            tot_gz += gz
            sizes.append(len(data))
            t = tiles.setdefault((ix, iy), {"x": ix, "y": iy, "hmax": 0.0, "lod": [None, None, None]})
            t["lod"][lod] = {"n": int(p1 - p0), "t": int(tri[p0:p1].sum()), "b": len(data), "gz": gz}
            if lod == 0:
                t["hmax"] = round(float(hgt[part_bldg[p0:p1]].max()), 1)
        sizes = np.array(sizes)
        summary[lod] = {"tiles": len(keys), "buildings": int(len(idx)), "prisms": n_parts, "vertices": int(len(coords)),
                        "triangles": int(tri.sum()), "bytes": int(tot_raw), "bytes_gzip": int(tot_gz),
                        "tile_bytes_p95": int(np.percentile(sizes, 95)), "tile_bytes_max": int(sizes.max()),
                        "tile_tri_p95": int(np.percentile([tiles[(int(k // 10_000_000), int(k % 10_000_000))]["lod"][lod]["t"] for k in keys], 95)),
                        "tile_tri_max": int(max(tiles[(int(k // 10_000_000), int(k % 10_000_000))]["lod"][lod]["t"] for k in keys))}

    # 시작 위치: LOD0 삼각형이 가장 많은 타일의 중심
    best = max(tiles.values(), key=lambda t: t["lod"][0]["t"])
    tb = b.total_bounds
    manifest = {
        "format": "BLDT", "version": VERSION, "region": region, "crs": "EPSG:5186", "tile_size": T,
        "source": Path(a.path).name, "created": date.today().isoformat(),
        "facade_enum": FACADE_ENUM,
        "floors": floor_info,
        "lods": [{"lod": 0, "name": "outline"}, {"lod": 1, "name": "box"},
                 {"lod": 2, "name": "box_large_only", "min_area_m2": LOD2_MIN_AREA, "min_height_m": LOD2_MIN_HEIGHT}],
        "bounds": [round(float(v), 1) for v in tb],
        "start": {"x": (best["x"] + 0.5) * T, "y": (best["y"] + 0.5) * T, "tile": [best["x"], best["y"]],
                  "rule": "LOD0 삼각형 최다 타일 중심"},
        "summary": summary,
        "tiles": sorted(tiles.values(), key=lambda t: (t["x"], t["y"])),
    }
    # 미니맵 개요 이미지와 법정동 라벨
    ov = render_overview(b, out_dir / "overview.png")
    manifest["overview"] = {"file": "overview.png", **ov}
    manifest["labels"] = area_labels(b) if "area_code" in b.columns else []
    # LOD2에 건물이 없는 타일은 파일 없음(null)
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, separators=(",", ":"))
    print(json.dumps({"start": manifest["start"], "summary": summary,
                      "manifest_bytes": (out_dir / "manifest.json").stat().st_size}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
