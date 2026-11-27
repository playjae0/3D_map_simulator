"""원본 GIS건물통합정보 SHP zip에서 시군구 하나를 잘라 같은 형식의 SHP zip으로 저장한다.

사용 예:
    python scripts/clip_region.py data/raw/AL_D010_11_20261109.zip 11710
    → data/raw/AL_D010_11710_20261109.zip  (송파구)

    python scripts/clip_region.py 입력.zip 11710 --out 결과.zip
    python scripts/clip_region.py 입력.zip 2 --field A6      # 다른 필드로 자르기(검증용)

방식: GDAL로 다시 쓰지 않고, DBF·SHP 레코드 바이트를 그대로 골라 새 파일로 이어 붙인다.
  - 필드 정의(이름·형식·폭)·인코딩(.cpg)·좌표계(.prj)가 원본과 똑같이 유지된다
  - zip 안의 파일을 처음부터 끝까지 한 번씩 순서대로 읽으므로, 서울 전체(DBF 수 GB 추정)도 메모리를 거의 쓰지 않는다
  - 바뀌는 것: SHP 레코드 번호(1부터 다시), SHP·SHX 헤더의 파일 길이와 범위, DBF 헤더의 레코드 수
기본 필드는 A23(원천 시군구코드). 값은 앞뒤 공백을 뺀 문자열로 정확히 비교한다.
"""
import argparse
import re
import shutil
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

CHUNK = 1 << 20


def member(z: zipfile.ZipFile, ext: str) -> str:
    names = [n for n in z.namelist() if n.lower().endswith(ext)]
    if len(names) != 1:
        sys.exit(f"zip 안에 {ext} 파일이 {len(names)}개입니다: {names}")
    return names[0]


def read_exact(f, n: int) -> bytes:
    b = f.read(n)
    if len(b) != n:
        raise EOFError("파일이 예상보다 짧습니다")
    return b


def select_dbf(z, name, field, value, out_path):
    """DBF를 순서대로 읽어 field == value인 레코드를 새 DBF로 쓰고, 고른 레코드 번호(0부터) 집합을 돌려준다."""
    keep = []
    with z.open(name) as f, open(out_path, "wb") as o:
        head = read_exact(f, 32)
        nrec, hlen, rlen = struct.unpack("<IHH", head[4:12])
        desc = read_exact(f, hlen - 32)
        offset, pos = None, 1                       # 레코드 첫 바이트는 삭제 표시
        for i in range((hlen - 33) // 32):
            d = desc[32 * i: 32 * i + 32]
            fname = d[:11].split(b"\0")[0].decode("ascii")
            if fname == field:
                offset, flen = pos, d[16]
            pos += d[16]
        if offset is None:
            sys.exit(f"DBF에 {field} 필드가 없습니다")
        if pos != rlen:
            sys.exit(f"DBF 레코드 길이 불일치: 필드 합 {pos}, 헤더 {rlen}")
        target = value.encode("ascii")
        o.write(head)
        o.write(desc)
        per = max(1, CHUNK // rlen)
        i = 0
        while i < nrec:
            n = min(per, nrec - i)
            block = read_exact(f, n * rlen)
            for k in range(n):
                rec = block[k * rlen:(k + 1) * rlen]
                if rec[0:1] != b"*" and rec[offset:offset + flen].strip() == target:
                    keep.append(i + k)
                    o.write(rec)
            i += n
        o.write(b"\x1a")
        o.seek(4)
        o.write(struct.pack("<I", len(keep)))
    return nrec, keep


def select_shp(z, name, nrec, keep, shp_path, shx_path):
    keep_set = set(keep)
    xmin = ymin = float("inf")
    xmax = ymax = float("-inf")
    with z.open(name) as f, open(shp_path, "wb") as o, open(shx_path, "wb") as x:
        head = bytearray(read_exact(f, 100))
        o.write(head)
        x.write(head)
        pos = 50                                     # 16비트 워드 단위 위치
        out_no = 0
        for i in range(nrec):
            rh = read_exact(f, 8)
            _, clen = struct.unpack(">ii", rh)
            content = read_exact(f, clen * 2)
            if i not in keep_set:
                continue
            out_no += 1
            o.write(struct.pack(">ii", out_no, clen))
            o.write(content)
            x.write(struct.pack(">ii", pos, clen))
            pos += 4 + clen
            stype = struct.unpack("<i", content[:4])[0]
            if stype != 0:                           # 빈 형상이 아니면 레코드 범위
                bx0, by0, bx1, by1 = struct.unpack("<4d", content[4:36])
                xmin, ymin, xmax, ymax = min(xmin, bx0), min(ymin, by0), max(xmax, bx1), max(ymax, by1)
        if f.read(1):
            sys.exit("SHP 레코드 수가 DBF와 다릅니다")
    if out_no == 0:
        xmin = ymin = xmax = ymax = 0.0
    for path, length in ((shp_path, pos), (shx_path, 50 + 4 * out_no)):
        with open(path, "r+b") as h:
            h.seek(24)
            h.write(struct.pack(">i", length))
            h.seek(36)
            h.write(struct.pack("<4d", xmin, ymin, xmax, ymax))
    return out_no, (xmin, ymin, xmax, ymax)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="원본 SHP zip (예: AL_D010_11_20261109.zip)")
    ap.add_argument("value", help="자를 값 (예: 11710 송파구)")
    ap.add_argument("--field", default="A23", help="비교할 DBF 필드 (기본 A23 원천 시군구코드)")
    ap.add_argument("--out", default=None, help="기본: 원본 옆에 AL_D010_<값>_<날짜>.zip")
    a = ap.parse_args()

    src = Path(a.src)
    m = re.match(r"(AL_D010)_\d+_(\d+)", src.stem)
    stem = f"{m.group(1)}_{a.value}_{m.group(2)}" if m else f"{src.stem}_{a.value}"
    out = Path(a.out) if a.out else src.with_name(f"{stem}.zip")
    if out.resolve() == src.resolve():
        sys.exit("결과 파일이 원본과 같은 경로입니다")
    stem = out.stem                                  # zip 안 파일 이름 = 결과 zip 이름

    with zipfile.ZipFile(src) as z, tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        nrec, keep = select_dbf(z, member(z, ".dbf"), a.field, a.value, tmp / f"{stem}.dbf")
        if not keep:
            sys.exit(f"{a.field} = {a.value} 인 레코드가 없습니다")
        n, bbox = select_shp(z, member(z, ".shp"), nrec, keep, tmp / f"{stem}.shp", tmp / f"{stem}.shx")
        for ext in (".prj", ".cpg"):
            try:
                (tmp / f"{stem}{ext}").write_bytes(z.read(member(z, ext)))
            except SystemExit:
                print(f"주의: 원본에 {ext} 파일이 없어 복사하지 않았습니다")
        out.parent.mkdir(parents=True, exist_ok=True)
        part = out.with_suffix(".zip.part")
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zo:
            for p in sorted(tmp.iterdir()):
                zo.write(p, p.name)
        shutil.move(part, out)

    print(f"원본 {nrec:,}건 중 {a.field} = {a.value}: {n:,}건")
    print(f"범위: {bbox[0]:.1f}, {bbox[1]:.1f} ~ {bbox[2]:.1f}, {bbox[3]:.1f}")
    print(f"저장: {out} ({out.stat().st_size / 1024 / 1024:.2f} MB)")


if __name__ == "__main__":
    main()
