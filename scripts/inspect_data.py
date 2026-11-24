"""1단계 데이터 점검: GIS건물통합정보(AL_D010) SHP zip의 구조·속성·형상 품질을 확인한다.

사용 예:
    python scripts/inspect_data.py data/raw/AL_D010_36_20261109.zip
    python scripts/inspect_data.py data/raw/AL_D010_36_20261109.zip --json data/processed/inspect_36.json

확인 내용
  1. zip 구성, .cpg/.prj, DBF 헤더 필드 정의, 인코딩(원시 바이트 디코딩 시험)
  2. 필드별 결측·고유값·상위값, 필드 의미 검증용 정합성 검사(코드 관계, 산술 관계)
  3. 높이(A16)·지상층수(A26)·주용도(A9) 결측률·분포·이상값, 높이/층수 비율 분포
  4. 형상: 빈 형상, 유효성, 극소 면적, 중복(동일 형상, 고중첩)
  5. 보조: 극소 형상의 정체, 면적·읍면동별 대장 연계율, 사용승인연도별 높이 결측, 층수→높이 대체식 교차검증
원본 파일은 읽기만 한다.
"""
import argparse
import io
import json
import struct
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

H, FL, USE, USE_CD = "A16", "A26", "A9", "A8"   # 높이, 지상층수, 주용도명, 주용도코드
H_BINS = [0, 1e-9, 0.5, 2, 3, 5, 10, 20, 30, 50, 100, 150, 200, 300, np.inf]
R_BINS = [0, 1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 6, 8, 10, 15, 20, np.inf]
AREA_TH = [1, 5, 10, 20, 30, 50]


def pct(s, qs=(0, 1, 5, 25, 50, 75, 95, 99, 99.9, 100)):
    s = pd.Series(s).dropna()
    return {f"p{q}": round(float(np.percentile(s, q)), 3) for q in qs} if len(s) else {}


def hist(s, bins):
    c = pd.cut(pd.Series(s).dropna(), bins, right=False).value_counts(sort=False)
    return {str(k): int(v) for k, v in c.items()}


def rate(n, d):
    return round(100 * n / d, 2) if d else None


# ---------- 1. 파일 구성 ----------
def inspect_zip(path):
    out = {"members": [], "cpg": None, "prj": None, "dbf_fields": []}
    with zipfile.ZipFile(path) as z:
        for i in z.infolist():
            out["members"].append({"name": i.filename, "size": i.file_size})
        names = z.namelist()
        cpg = [n for n in names if n.lower().endswith(".cpg")]
        prj = [n for n in names if n.lower().endswith(".prj")]
        dbf = [n for n in names if n.lower().endswith(".dbf")][0]
        if cpg:
            out["cpg"] = z.read(cpg[0]).decode("ascii", "replace").strip()
        if prj:
            out["prj"] = z.read(prj[0]).decode("ascii", "replace").strip()
        raw = z.read(dbf)
    ver, yy, mm, dd, nrec, hlen, rlen = struct.unpack("<BBBBIHH", raw[:12])
    out["dbf_header"] = {"version": hex(ver), "last_update_raw": [yy, mm, dd], "records": nrec,
                         "header_len": hlen, "record_len": rlen, "language_driver_id": raw[29]}
    fields = []
    for i in range((hlen - 33) // 32):
        d = raw[32 + 32 * i: 64 + 32 * i]
        fields.append({"name": d[:11].split(b"\0")[0].decode("ascii"), "type": chr(d[11]),
                       "length": d[16], "decimals": d[17]})
    out["dbf_fields"] = fields
    # 인코딩 시험: 레코드 영역 전체를 레코드 단위로 디코딩해 실패 건수를 센다
    body = raw[hlen: hlen + nrec * rlen]
    enc = {}
    for e in ("utf-8", "cp949", "euc-kr"):
        bad = 0
        for k in range(nrec):
            try:
                body[k * rlen:(k + 1) * rlen].decode(e)
            except UnicodeDecodeError:
                bad += 1
        enc[e] = {"records_failed": bad}
    out["encoding_test"] = enc
    out["non_ascii_bytes"] = int(sum(1 for b in body[:5_000_000] if b >= 0x80))
    return out


# ---------- 2. 필드 프로파일·정합성 ----------
def profile(df):
    prof = {}
    for c in df.columns:
        s = df[c]
        p = {"dtype": str(s.dtype), "null": int(s.isna().sum()), "unique": int(s.nunique())}
        if s.dtype == object or str(s.dtype).startswith("str"):
            p["empty_str"] = int((s.astype("string").str.strip() == "").sum())
            p["len_min_max"] = [int(s.dropna().str.len().min()), int(s.dropna().str.len().max())] if s.notna().any() else None
        elif np.issubdtype(s.dtype, np.number):
            p["zero"] = int((s == 0).sum())
            p["min"], p["max"] = float(s.min()), float(s.max())
        p["top"] = {str(k): int(v) for k, v in s.value_counts(dropna=False).head(8).items()}
        prof[c] = p
    return prof


def consistency(g):
    df = g
    n = len(df)
    r = {}
    a2 = df.A2.astype(str)
    r["A2[:10]==A3 (PNU 앞 10자리=법정동코드)"] = rate(int((a2.str[:10] == df.A3).sum()), n)
    pnu_san = a2.str[10].map({"1": "1", "2": "2"})
    r["A2[10]==A6 (PNU 11번째=대장구분 1일반/2산)"] = rate(int((pnu_san == df.A6).sum()), n)
    bon = a2.str[11:15].astype(int).astype(str)
    bu = a2.str[15:19].astype(int)
    jibun = np.where(bu > 0, bon + "-" + bu.astype(str), bon)
    r["A5==PNU 본번-부번 (지번)"] = rate(int((df.A5 == jibun).sum()), n)
    r["A3[:5]==A23 (원천 시군구코드)"] = rate(int((df.A3.str[:5] == df.A23).sum()), n)
    r["A6→A7 대응"] = df.groupby("A6").A7.unique().apply(list).to_dict()

    def one_to_one(a, b):
        m = df[[a, b]].dropna().drop_duplicates()
        return {"pairs": len(m), "codes": int(m[a].nunique()), "names": int(m[b].nunique()),
                "code_without_name": int((df[a].notna() & df[b].isna()).sum())}
    r["A8↔A9 (용도코드↔용도명)"] = one_to_one("A8", "A9")
    r["A10↔A11 (구조코드↔구조명)"] = one_to_one("A10", "A11")

    # 산술 관계: 건폐율 = 건축면적/대지면적×100, 용적률 = 연면적/대지면적×100
    m = (df.A15 > 0) & (df.A12 > 0)
    bcr = df.A12[m] / df.A15[m] * 100
    r["A17≈A12/A15×100 (건폐율), |오차|<0.1 비율"] = rate(int((abs(bcr - df.A17[m]) < 0.1).sum()), int(m.sum()))
    m2 = (df.A15 > 0) & (df.A14 > 0)
    far = df.A14[m2] / df.A15[m2] * 100
    r["A18≈A14/A15×100 (용적률), |오차|<0.1 비율"] = rate(int((abs(far - df.A18[m2]) < 0.1).sum()), int(m2.sum()))
    m3 = (df.A12 > 0) & (df.A14 > 0)
    r["A14>=A12 (연면적>=건축면적) 비율"] = rate(int((df.A14[m3] >= df.A12[m3] - 0.01).sum()), int(m3.sum()))
    m4 = m3 & (df[FL] > 0)
    r["A14/A12 vs A26+A27 상관계수 (연면적/건축면적≈층수)"] = round(float(np.corrcoef(
        (df.A14[m4] / df.A12[m4]).clip(upper=100), (df[FL][m4] + df.A27[m4].fillna(0)))[0, 1]), 3)
    # 건축면적 vs 도형 면적
    fa = g.geometry.area
    m5 = df.A12 > 0
    ratio = df.A12[m5] / fa[m5]
    r["A12/도형면적 분포"] = pct(ratio, (1, 5, 25, 50, 75, 95, 99))
    # 사용승인일 vs A1 앞 4자리
    yr = pd.to_datetime(df.A13, errors="coerce").dt.year
    a1y = pd.to_numeric(df.A1.str[:4], errors="coerce")
    m6 = yr.notna()
    r["A13 날짜 파싱 성공(비결측 중)"] = rate(int(m6.sum()), int(df.A13.notna().sum()))
    r["A1[:4]==A13 연도 (비결측 중)"] = rate(int((a1y[m6] == yr[m6]).sum()), int(m6.sum()))
    r["A1[:4]=='0000' 비율 / A13 결측 비율"] = [rate(int((df.A1.str[:4] == "0000").sum()), n), rate(int(df.A13.isna().sum()), n)]
    r["A19(건축물ID) 결측 ↔ A8 결측 일치"] = rate(int((df.A19.isna() == df.A8.isna()).sum()), n)
    r["A21 접두 4자리"] = df.A21.str[:4].value_counts(dropna=False).head(5).to_dict()
    r["A21 길이"] = df.A21.str.len().value_counts(dropna=False).head(5).to_dict()
    r["A22 값"] = [str(v) for v in df.A22.dropna().unique()[:3]]
    return r


# ---------- 3. 높이·층수·주용도 ----------
def height_floor_use(df):
    n = len(df)
    h, fl = df[H], df[FL]
    linked = df.A19.notna()           # 건축물대장 연계 여부
    out = {"n": n, "linked_to_register": int(linked.sum()), "linked_rate": rate(int(linked.sum()), n)}

    def miss(s, mask=None):
        s = s if mask is None else s[mask]
        return {"null": int(s.isna().sum()), "zero": int((s == 0).sum()),
                "missing_rate": rate(int((s.isna() | (s == 0)).sum()), len(s))}
    out["height_missing"] = {"all": miss(h), "linked": miss(h, linked), "unlinked": miss(h, ~linked)}
    out["floors_missing"] = {"all": miss(fl), "linked": miss(fl, linked), "unlinked": miss(fl, ~linked)}
    use_m = df[USE].isna() | (df[USE].astype("string").str.strip() == "")
    out["use_missing"] = {"all": rate(int(use_m.sum()), n), "linked": rate(int(use_m[linked].sum()), int(linked.sum()))}

    hp, fp = h > 0, fl > 0
    out["cross"] = {"h>0&fl>0": int((hp & fp).sum()), "h>0&fl=0": int((hp & ~fp).sum()),
                    "h=0&fl>0": int((~hp & fp).sum()), "h=0&fl=0": int((~hp & ~fp).sum())}
    out["cross_linked"] = {"h>0&fl>0": int((hp & fp & linked).sum()), "h>0&fl=0": int((hp & ~fp & linked).sum()),
                           "h=0&fl>0": int((~hp & fp & linked).sum()), "h=0&fl=0": int((~hp & ~fp & linked).sum())}

    out["height_pct(h>0)"] = pct(h[hp])
    out["height_hist(all)"] = hist(h, H_BINS)
    out["floors_pct(fl>0)"] = pct(fl[fp])
    out["floors_hist(all)"] = {str(k): int(v) for k, v in fl.value_counts().sort_index().items()}
    out["height_decimals"] = {"integer": int((h[hp] % 1 == 0).sum()), "non_integer": int((h[hp] % 1 != 0).sum())}

    # 이상값 후보
    an = {}
    an["0<h<0.5"] = int(((h > 0) & (h < 0.5)).sum())
    an["0.5<=h<2"] = int(((h >= 0.5) & (h < 2)).sum())
    an["h>300"] = int((h > 300).sum())
    an["h>100"] = int((h > 100).sum())
    both = hp & fp
    ratio = (h / fl)[both]
    out["ratio_pct(h/fl)"] = pct(ratio)
    out["ratio_hist"] = hist(ratio, R_BINS)
    for lo in (1.5, 2.0, 2.2):
        an[f"ratio<{lo}"] = int((ratio < lo).sum())
    for hi in (6, 8, 10, 15):
        an[f"ratio>{hi}"] = int((ratio > hi).sum())
        an[f"ratio>{hi}&fl>=2"] = int(((ratio > hi) & (fl[both] >= 2)).sum())
        an[f"ratio>{hi}&fl>=4"] = int(((ratio > hi) & (fl[both] >= 4)).sum())
    an["h>0&fl=0 중 h>=20"] = int((hp & ~fp & (h >= 20)).sum())
    out["anomaly_candidates"] = an

    # 상·하위 사례
    cols = ["A0", H, FL, "A27", USE, "A12", "A14", "A13", "A24", "A25"]
    d = df.loc[both, cols].assign(ratio=ratio.round(2))
    out["examples_high_h"] = d.sort_values(H, ascending=False).head(10).astype(str).to_dict("records")
    out["examples_low_ratio"] = d.sort_values("ratio").head(10).astype(str).to_dict("records")
    out["examples_high_ratio_multistory"] = d[d[FL] >= 2].sort_values("ratio", ascending=False).head(10).astype(str).to_dict("records")
    hz = df.loc[hp & ~fp, cols]
    out["examples_h_pos_fl_zero"] = hz.sort_values(H, ascending=False).head(5).astype(str).to_dict("records")

    # 주용도별
    g = df.assign(_h=hp, _f=fp, _r=(h / fl).where(both))
    by = g.groupby(df[USE].fillna("(결측)")).agg(
        n=("A0", "size"), h_present=("_h", "mean"), fl_present=("_f", "mean"),
        h_med=(H, lambda s: float(s[s > 0].median()) if (s > 0).any() else None),
        r_p10=("_r", lambda s: float(s.quantile(0.1)) if s.notna().any() else None),
        r_med=("_r", lambda s: float(s.median()) if s.notna().any() else None),
        r_p90=("_r", lambda s: float(s.quantile(0.9)) if s.notna().any() else None),
    ).sort_values("n", ascending=False)
    by["h_present"] = (by.h_present * 100).round(1)
    by["fl_present"] = (by.fl_present * 100).round(1)
    out["by_use"] = by.round(2).reset_index().rename(columns={USE: "use"}).to_dict("records")

    # 층수별 비율 (단층/다층 구분용)
    gb = pd.DataFrame({"fl": fl[both], "r": ratio})
    gb["fl_bin"] = pd.cut(gb.fl, [0, 1, 2, 3, 5, 10, 20, 100], labels=["1", "2", "3", "4-5", "6-10", "11-20", "21+"])
    out["ratio_by_floors"] = gb.groupby("fl_bin", observed=True).r.describe(percentiles=[.05, .5, .95]).round(2).reset_index().astype(str).to_dict("records")
    return out


# ---------- 4. 형상 ----------
def geometry_quality(g):
    geom = np.asarray(g.geometry.values)
    n = len(geom)
    out = {"n": n, "geom_types": g.geometry.geom_type.value_counts(dropna=False).to_dict()}
    null = shapely.is_missing(geom)
    empty = shapely.is_empty(geom) & ~null
    out["null"], out["empty"] = int(null.sum()), int(empty.sum())
    ok = ~null & ~empty
    valid = shapely.is_valid(geom)
    out["invalid"] = int((ok & ~valid).sum())
    reasons = pd.Series(shapely.is_valid_reason(geom[ok & ~valid]))
    out["invalid_reasons"] = reasons.str.replace(r"\[.*\]", "", regex=True).value_counts().to_dict()
    fixed = shapely.make_valid(geom[ok & ~valid])
    out["invalid_area_change_after_make_valid(p50,max %)"] = [
        round(float(np.median(np.abs(shapely.area(fixed) / shapely.area(geom[ok & ~valid]) - 1) * 100)), 3) if len(fixed) else None,
        round(float(np.max(np.abs(shapely.area(fixed) / shapely.area(geom[ok & ~valid]) - 1) * 100)), 3) if len(fixed) else None]
    out["holes"] = int((shapely.get_num_interior_rings(geom[ok]) > 0).sum())
    nv = shapely.get_num_coordinates(geom[ok])
    out["vertices_pct"] = pct(nv)
    area = shapely.area(geom)
    out["area_pct"] = pct(area[ok])
    out["area_below"] = {f"<{t}m2": [int((area[ok] < t).sum()), rate(int((area[ok] < t).sum()), int(ok.sum()))] for t in AREA_TH}
    linked = g.A19.notna().values
    out["area_below_linked"] = {f"<{t}m2": int((area[ok & linked] < t).sum()) for t in AREA_TH}
    out["area_below_unlinked"] = {f"<{t}m2": int((area[ok & ~linked] < t).sum()) for t in AREA_TH}

    # 중복 1: 동일 형상 (정규화 후 WKB 동일)
    norm = shapely.normalize(shapely.set_precision(geom[ok], 0.001))
    wkb = pd.Series(shapely.to_wkb(norm), index=np.flatnonzero(ok))
    dup = wkb.duplicated(keep=False)
    grp = wkb[dup].groupby(wkb[dup]).size()
    out["exact_dup"] = {"records_in_groups": int(dup.sum()), "groups": int(len(grp)),
                        "excess_records": int(dup.sum() - len(grp)), "group_size_max": int(grp.max()) if len(grp) else 0}
    if dup.any():
        idx = wkb[dup].index
        sub = g.iloc[idx]
        k = wkb[dup].map(lambda b: hash(b))
        same_attr = sub.assign(_k=k.values).groupby("_k").apply(
            lambda d: d.drop(columns=["geometry", "A0"]).astype(str).nunique().max() == 1, include_groups=False)
        out["exact_dup"]["groups_all_attrs_equal(except A0)"] = int(same_attr.sum())
        out["exact_dup"]["groups_with_register_link"] = int(sub.assign(_k=k.values).groupby("_k").A19.apply(lambda s: s.notna().any()).sum())
        out["exact_dup"]["examples"] = sub.assign(_k=k.values).sort_values("_k")[["A0", "A1", "A19", "A21", H, FL, USE, "A24", "A25"]].head(12).astype(str).to_dict("records")

    # 중복 2: 고중첩 (IoU), 상호 포함
    gv = shapely.make_valid(geom[ok])
    tree = shapely.STRtree(gv)
    a, b = tree.query(gv, predicate="intersects")
    m = a < b
    a, b = a[m], b[m]
    inter = shapely.area(shapely.intersection(gv[a], gv[b]))
    ar = shapely.area(gv)
    union = ar[a] + ar[b] - inter
    iou = np.where(union > 0, inter / union, 0)
    cover = np.where(np.minimum(ar[a], ar[b]) > 0, inter / np.minimum(ar[a], ar[b]), 0)
    out["overlap_pairs"] = {
        "intersecting_pairs": int(len(a)),
        "pairs_inter_area>0.01m2": int((inter > 0.01).sum()),
        "iou>=0.99": int((iou >= 0.99).sum()), "iou>=0.9": int((iou >= 0.9).sum()), "iou>=0.5": int((iou >= 0.5).sum()),
        "smaller_covered>=0.9": int((cover >= 0.9).sum()),
        "buildings_in_iou>=0.9_pairs": int(len(np.unique(np.r_[a[iou >= 0.9], b[iou >= 0.9]]))),
        "buildings_in_any_overlap>1m2": int(len(np.unique(np.r_[a[inter > 1], b[inter > 1]]))),
    }
    # 고중첩(0.9<=IoU<0.99) 쌍의 속성 관계
    okidx = np.flatnonzero(ok)
    hi = (iou >= 0.9) & (iou < 0.99)
    if hi.any():
        ga, gb = g.iloc[okidx[a[hi]]].reset_index(drop=True), g.iloc[okidx[b[hi]]].reset_index(drop=True)
        out["overlap_pairs"]["iou0.9-0.99_same_A19"] = int(((ga.A19 == gb.A19) & ga.A19.notna()).sum())
        out["overlap_pairs"]["iou0.9-0.99_one_linked_one_not"] = int((ga.A19.isna() ^ gb.A19.isna()).sum())
        out["overlap_pairs"]["iou0.9-0.99_both_unlinked"] = int((ga.A19.isna() & gb.A19.isna()).sum())

    # 식별자 중복
    out["id_dup"] = {c: int(g[c].dropna().duplicated().sum()) for c in ("A0", "A1", "A19", "A21")}
    s19 = g.A19.dropna()
    out["A19_multi_polygon_groups"] = int((s19.value_counts() > 1).sum())
    s21 = g.A21.dropna()
    vc21 = s21.value_counts()
    out["A21_multi_record_groups"] = {"groups": int((vc21 > 1).sum()), "records": int(vc21[vc21 > 1].sum()), "max": int(vc21.max())}
    # 같은 A21을 공유하는 레코드가 같은 형상인지
    multi = g[g.A21.isin(vc21[vc21 > 1].index)]
    if len(multi):
        same = multi.groupby("A21").geometry.apply(lambda s: bool(all(s.iloc[0].equals(x) for x in s.iloc[1:])))
        out["A21_multi_record_groups"]["same_geometry_groups"] = int(same.sum())
    return out


# ---------- 5. 보조 분석: 수록 범위, 결측 원인, 층수 대체식 비교 ----------
def supplementary(g):
    out = {}
    area = g.geometry.area
    emd = g.A4.str.split().str[1]
    dong = emd.str.endswith("동")
    yr = pd.to_datetime(g.A13, errors="coerce").dt.year
    linked = g.A19.notna()

    tiny = area < 1
    b = g.geometry[tiny].bounds
    out["tiny_lt1m2"] = {"n": int(tiny.sum()), "linked": int((tiny & linked).sum()), "A21_null": int((tiny & g.A21.isna()).sum()),
                         "bbox_width_p50": round(float((b.maxx - b.minx).median()), 3),
                         "height_present_rate": rate(int((g[H][tiny] > 0).sum()), int(tiny.sum()))}
    out["linkage_by_area"] = {}
    for lo, hi in [(0, 1), (1, 10), (10, 20), (20, 50), (50, 100), (100, 300), (300, 1000), (1000, 1e12)]:
        m = (area >= lo) & (area < hi)
        out["linkage_by_area"][f"[{lo},{hi})"] = {"n": int(m.sum()), "linked%": rate(int((m & linked).sum()), int(m.sum())),
                                                   "h>0%": rate(int((m & (g[H] > 0)).sum()), int(m.sum()))}
    by = pd.DataFrame({"emd": emd, "dong": dong, "area": area, "apt": g[USE] == "공동주택", "fl": g[FL], "h": g[H], "yr": yr, "linked": linked})
    out["by_emd"] = by.groupby("emd").agg(
        n=("area", "size"), footprint_km2=("area", lambda s: round(s.sum() / 1e6, 3)), linked_pct=("linked", lambda s: round(100 * s.mean(), 1)),
        apt=("apt", "sum"), fl_max=("fl", "max"), h_max=("h", "max"), approval_year_max=("yr", "max"),
    ).sort_values("n", ascending=False).reset_index().to_dict("records")
    bins = [1900, 1990, 2000, 2005, 2010, 2013, 2016, 2020, 2100]
    out["approval_year_hist"] = {"dong": hist(yr[dong], bins), "eupmyeon": hist(yr[~dong], bins)}
    d = pd.DataFrame({"yr": yr[linked], "h": g[H][linked]})
    d["yb"] = pd.cut(d.yr, [1900, 1980, 1990, 2000, 2005, 2010, 2015, 2100])
    out["linked_height_present_by_approval_year"] = {str(k): v for k, v in
                                                     d.groupby("yb", observed=True).h.apply(lambda s: rate(int((s > 0).sum()), len(s))).items()}

    # 층수→높이 대체식 비교 (대장 연계, h>0, fl>0, 2<=h/fl<=10 표본, 5겹 교차검증)
    m = linked & (g[H] > 0) & (g[FL] > 0) & (g[H] / g[FL]).between(2, 10)
    x, y = g[FL][m].to_numpy(float), g[H][m].to_numpy(float)
    use = g[USE][m].fillna("NA").to_numpy()

    def lad(xx, yy):
        A = np.c_[np.ones_like(xx), xx]
        w = np.ones_like(xx)
        for _ in range(50):
            W = np.sqrt(w)
            c = np.linalg.lstsq(A * W[:, None], yy * W, rcond=None)[0]
            w = 1 / np.maximum(np.abs(yy - A @ c), 1e-3)
        return c
    c_all = lad(x, y)
    out["substitution_sample_n"] = int(m.sum())
    out["lad_fit_all"] = {"intercept": round(float(c_all[0]), 3), "per_floor": round(float(c_all[1]), 3)}
    out["median_h_by_floors"] = {int(k): round(float(v), 2) for k, v in pd.Series(y).groupby(x).median().items()}
    idx = np.random.default_rng(0).permutation(len(x))
    scores = {k: [] for k in ("fl*3", "fl*median_ratio", "lad_a+b*fl", "fl*use_median_ratio")}
    tall = {k: [] for k in scores}
    for f in np.array_split(idx, 5):
        tr = np.setdiff1d(idx, f)
        rmed = np.median(y[tr] / x[tr])
        c = lad(x[tr], y[tr])
        ur = pd.Series(y[tr] / x[tr]).groupby(use[tr]).median()
        preds = {"fl*3": 3 * x[f], "fl*median_ratio": rmed * x[f], "lad_a+b*fl": c[0] + c[1] * x[f],
                 "fl*use_median_ratio": pd.Series(use[f]).map(ur).fillna(rmed).to_numpy() * x[f]}
        for k, p in preds.items():
            e = p - y[f]
            scores[k].append([np.median(np.abs(e)), np.median(np.abs(e) / y[f]) * 100, np.mean(e)])
            t = x[f] >= 10
            tall[k].append(np.median(np.abs(e[t]) / y[f][t]) * 100 if t.any() else np.nan)
    out["substitution_cv"] = {k: {"MedAE_m": round(float(np.mean([s[0] for s in v])), 2),
                                  "MedAPE_%": round(float(np.mean([s[1] for s in v])), 1),
                                  "bias_m": round(float(np.mean([s[2] for s in v])), 2),
                                  "MedAPE_%_fl>=10": round(float(np.nanmean(tall[k])), 1)} for k, v in scores.items()}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--encoding", default=None, help="DBF 인코딩. 생략 시 .cpg를 따른다")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    res = {"input": a.path, "zip": inspect_zip(a.path)}
    g = gpd.read_file(a.path, encoding=a.encoding) if a.encoding else gpd.read_file(a.path)
    res["crs"] = {"epsg": g.crs.to_epsg(), "name": g.crs.name, "bounds": [round(v, 1) for v in g.total_bounds]}
    df = g.drop(columns="geometry")
    res["replacement_char_in_strings"] = int(sum(df[c].astype("string").str.contains("�", regex=False).sum()
                                                for c in df.columns if df[c].dtype == object or str(df[c].dtype).startswith("str")))
    res["profile"] = profile(df)
    res["consistency"] = consistency(g)
    res["height_floor_use"] = height_floor_use(df)
    res["geometry"] = geometry_quality(g)
    res["supplementary"] = supplementary(g)

    txt = json.dumps(res, ensure_ascii=False, indent=1, default=str)
    print(txt)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            f.write(txt)


if __name__ == "__main__":
    main()
