"""미니맵용 2D 개요 이미지와 법정동 라벨 위치. tile.py가 타일과 함께 만든다.

단독 실행(미리보기):
    python scripts/overview.py data/processed/buildings_36.parquet out.png

개요 이미지: 북쪽이 위, 전체 건물 범위(+여백 2%). 3배 크게 그린 뒤 줄여서 작은 건물도 옅게 남긴다.
라벨: 법정동(리) 코드별로 건물 중심점의 중앙값에 가장 가까운 건물 중심점(동 밖에 찍히지 않게).
"""
import sys

import geopandas as gpd
import numpy as np
import shapely
from PIL import Image, ImageDraw

BG = (29, 35, 41)
# 높이 구간별 색: 낮은 건물부터 그려 높은 건물이 위에 오게 한다
HEIGHT_COLORS = [(0, (120, 130, 138)), (10, (176, 186, 193)), (30, (232, 236, 239)), (60, (255, 214, 140))]


def render_overview(b: gpd.GeoDataFrame, out_png, max_px: int = 512, ss: int = 3) -> dict:
    x0, y0, x1, y1 = b.total_bounds
    pad = 0.02 * max(x1 - x0, y1 - y0)
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    mpp = max(x1 - x0, y1 - y0) / max_px                    # m/픽셀
    w, h = int(np.ceil((x1 - x0) / mpp)), int(np.ceil((y1 - y0) / mpp))
    img = Image.new("RGB", (w * ss, h * ss), BG)
    draw = ImageDraw.Draw(img)
    height = b.height_m.to_numpy(float)
    order = np.argsort(height, kind="stable")
    geoms = np.asarray(b.geometry.values)[order]
    height = height[order]
    k = ss / mpp
    for geom, hm in zip(geoms, height):
        color = [c for t, c in HEIGHT_COLORS if hm >= t][-1]
        for poly in shapely.get_parts(geom):
            xy = np.asarray(poly.exterior.coords)
            px = np.column_stack([(xy[:, 0] - x0) * k, (y1 - xy[:, 1]) * k])
            if len(px) >= 3:
                draw.polygon([tuple(p) for p in px], fill=color)
    img = img.resize((w, h), Image.Resampling.LANCZOS)
    img.save(out_png, optimize=True)
    return {"bounds": [round(float(v), 1) for v in (x0, y0, x1, y1)], "width": w, "height": h,
            "m_per_px": round(float(mpp), 2)}


def area_labels(b: gpd.GeoDataFrame) -> list:
    c = shapely.centroid(np.asarray(b.geometry.values))
    df = b[["area_code", "area_name"]].assign(x=shapely.get_x(c), y=shapely.get_y(c)).dropna(subset=["area_code"])
    out = []
    for code, g in df.groupby("area_code"):
        mx, my = g.x.median(), g.y.median()
        i = int(np.argmin((g.x.to_numpy() - mx) ** 2 + (g.y.to_numpy() - my) ** 2))
        name = g.area_name.mode().iloc[0] if g.area_name.notna().any() else str(code)
        out.append({"code": str(code), "name": str(name), "x": round(float(g.x.iloc[i]), 1),
                    "y": round(float(g.y.iloc[i]), 1), "n": int(len(g))})
    return sorted(out, key=lambda r: -r["n"])                # 건물 많은 동이 먼저(겹치면 우선 표시)


if __name__ == "__main__":
    bb = gpd.read_parquet(sys.argv[1])
    bb = bb[bb.h_src != "excluded"]
    print(render_overview(bb, sys.argv[2]))
    print(area_labels(bb)[:5])
