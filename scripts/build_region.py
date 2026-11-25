"""지역 하나를 처음부터 끝까지 처리한다: (점검) → 정제 → 타일·개요 이미지·라벨.

사용 예:
    python scripts/build_region.py data/raw/AL_D010_11710_20261109.zip            # 송파구
    python scripts/build_region.py data/raw/AL_D010_11710_20261109.zip --inspect  # 1단계 점검도 함께

결과(지역 코드 = 파일 이름의 AL_D010_<코드>):
    data/processed/buildings_<코드>.parquet (+ .meta.json)
    data/processed/tiles/<코드>/            (manifest.json, overview.png, 0~2/*.bin)
    data/processed/inspect_<코드>.json      (--inspect일 때)
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(*args):
    print("$", " ".join(str(a) for a in args), flush=True)
    subprocess.run([sys.executable, *map(str, args)], check=True, stdout=subprocess.DEVNULL)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("zip")
    ap.add_argument("--inspect", action="store_true", help="scripts/inspect_data.py도 실행")
    a = ap.parse_args()

    m = re.search(r"AL_D010_(\d+)", Path(a.zip).name)
    if not m:
        sys.exit("파일 이름에서 지역 코드(AL_D010_<코드>_...)를 찾지 못했습니다")
    region = m.group(1)
    if a.inspect:
        run(HERE / "inspect_data.py", a.zip, "--json", f"data/processed/inspect_{region}.json")
    run(HERE / "refine.py", a.zip)
    run(HERE / "tile.py", f"data/processed/buildings_{region}.parquet")

    meta = json.load(open(f"data/processed/buildings_{region}.meta.json", encoding="utf-8"))
    man = json.load(open(f"data/processed/tiles/{region}/manifest.json", encoding="utf-8"))
    print(f"\n지역 {region}: 건물 {meta['counts']['total']:,}건, h_src {meta['counts']['h_src']}")
    for lod, s in man["summary"].items():
        print(f"  LOD{lod}: 타일 {s['tiles']}, 삼각형 {s['triangles']:,}, {s['bytes'] / 1e6:.2f} MB")
    print(f"  시작 위치 {man['start']['x']:.0f}, {man['start']['y']:.0f} / 라벨 {len(man.get('labels', []))}개")
    print(f"\n뷰어: cd viewer && npm run dev  → 주소 뒤에 ?region={region}")
    print(f"artifact: cd viewer && REGION={region} npm run build:artifact")


if __name__ == "__main__":
    main()
