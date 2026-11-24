"""건물 외곽선의 타일 밀도와 LOD1 extrude 시 삼각형 수를 측정한다.

사용 예:
    python scripts/measure_density.py data/raw/AL_D010_36_xxxx.zip --encoding cp949
    python scripts/measure_density.py buildings.parquet --tile 250 500 1000 --radii 500 1000 2000

입력: SHP(zip 가능) 또는 GeoParquet. 좌표는 EPSG:5186(미터)로 변환해 계산한다.
삼각형 수 근사: 외곽선 변 수 e, 구멍 수 h일 때 벽 2e + 지붕 (e - 2 + 2h). 바닥면은 그리지 않는다고 가정한다.
"""
import argparse
import json
import sys

import geopandas as gpd
import numpy as np
import shapely


def load(path: str, encoding: str | None) -> gpd.GeoDataFrame:
    if path.endswith(".parquet"):
        gdf = gpd.read_parquet(path)
    else:
        gdf = gpd.read_file(path, encoding=encoding) if encoding else gpd.read_file(path)
    if gdf.crs is None:
        sys.exit("CRS가 없습니다. .prj 파일을 확인하세요.")
    return gdf.to_crs(5186)


def triangles(geoms: np.ndarray) -> np.ndarray:
    # 건물(멀티폴리곤) 단위 삼각형 수
    parts = shapely.get_parts(geoms, return_index=True)
    polys, idx = parts
    n_coords = shapely.get_num_coordinates(polys)          # 닫힌 링 좌표 포함
    n_holes = shapely.get_num_interior_rings(polys)
    n_rings = 1 + n_holes
    e = n_coords - n_rings                                 # 변(고유 꼭짓점) 수
    t = 2 * e + (e - 2 + 2 * n_holes)
    out = np.zeros(len(geoms), dtype=np.int64)
    np.add.at(out, idx, np.maximum(t, 0))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--encoding", default=None)
    ap.add_argument("--tile", type=int, nargs="+", default=[250, 500, 1000])
    ap.add_argument("--radii", type=int, nargs="+", default=[500, 1000, 2000, 3000])
    ap.add_argument("--top", type=int, default=30, help="반경 측정 시 후보로 쓸 최밀집 타일 수")
    ap.add_argument("--json", default=None, help="결과 저장 경로")
    a = ap.parse_args()

    gdf = load(a.path, a.encoding)
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
    geoms = gdf.geometry.values
    tri = triangles(np.asarray(geoms))
    c = shapely.centroid(np.asarray(geoms))
    x, y = shapely.get_x(c), shapely.get_y(c)

    res = {
        "input": a.path,
        "buildings": int(len(gdf)),
        "triangles_total": int(tri.sum()),
        "tiles": {},
        "densest_radius_triangles": {},
    }
    for T in a.tile:
        ix, iy = np.floor(x / T).astype(np.int64), np.floor(y / T).astype(np.int64)
        key = ix * 10_000_000 + iy
        u, inv = np.unique(key, return_inverse=True)
        nb = np.bincount(inv)
        nt = np.bincount(inv, weights=tri)
        res["tiles"][T] = {
            "count": int(len(u)),
            "bldg_mean": round(float(nb.mean()), 1),
            "bldg_p95": float(np.percentile(nb, 95)),
            "bldg_max": int(nb.max()),
            "tri_mean": round(float(nt.mean()), 1),
            "tri_p95": float(np.percentile(nt, 95)),
            "tri_max": int(nt.max()),
        }

    # 최밀집 지점 주변 반경별 삼각형 수 (500m 타일 상위 후보의 중심 기준)
    T = 500
    ix, iy = np.floor(x / T).astype(np.int64), np.floor(y / T).astype(np.int64)
    key = ix * 10_000_000 + iy
    u, inv = np.unique(key, return_inverse=True)
    nt = np.bincount(inv, weights=tri)
    cand = np.argsort(nt)[-a.top:]
    centers = [((u[k] // 10_000_000 + 0.5) * T, (u[k] - (u[k] // 10_000_000) * 10_000_000 + 0.5) * T) for k in cand]
    for R in a.radii:
        best = 0
        for cx, cy in centers:
            m = (x - cx) ** 2 + (y - cy) ** 2 < R * R
            best = max(best, int(tri[m].sum()))
        res["densest_radius_triangles"][R] = best

    print(json.dumps(res, ensure_ascii=False, indent=2))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
