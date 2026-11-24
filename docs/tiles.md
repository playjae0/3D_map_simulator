# 타일·LOD 형식

생성: `scripts/tile.py` (입력은 `docs/schema.md`의 건물 테이블). 결과: `data/processed/tiles/<지역>/`.

```
tiles/<지역>/manifest.json
tiles/<지역>/<lod>/<x>_<y>.bin      x = floor(X / 500), y = floor(Y / 500)  (EPSG:5186)
```

- 격자: EPSG:5186 기준 500m 정사각형. 건물은 외곽선 중심점이 속한 타일에 통째로 배정한다(자르지 않음). 따라서 건물이 타일 경계를 넘을 수 있다
- `h_src=excluded` 건물은 넣지 않는다

## LOD

| lod | 이름 | 형상 | 대상 |
|---|---|---|---|
| 0 | outline | 원래 외곽선(1cm 이내 중복 꼭짓점만 제거), 구멍 포함 | 전체 |
| 1 | box | 최소 회전 사각형(`oriented_envelope`) | 전체 |
| 2 | box_large_only | 최소 회전 사각형 | 면적 100m² 이상 또는 높이 12m 이상 |

LOD2에 남는 건물이 없는 타일은 파일을 만들지 않고 manifest에 `null`로 둔다.

## 바이너리 `.bin` (BLDT v2, little-endian)

외곽선과 높이만 담는다. 벽·지붕 메시는 기기에서 만든다(`decisions.md`의 메시 저장 방식).

| 오프셋 | 타입 | 내용 |
|---|---|---|
| 0 | char[4] | `BLDT` |
| 4 | u8 | 버전 = 2 (v1에 층수 배열 추가) |
| 5 | u8 | lod |
| 6 | u16 | 예약(0) |
| 8 | u32 | nPrisms (폴리곤 파트 수, MultiPolygon은 파트마다 1개) |
| 12 | u32 | nRings |
| 16 | u32 | nVerts |
| 20 | u32 | 예약(0) |
| 24 | i32 | 타일 x |
| 28 | i32 | 타일 y |
| 32 | u32[nPrisms+1] | 프리즘별 링 시작 위치 |
| | u32[nRings+1] | 링별 꼭짓점 시작 위치 |
| | f32[nVerts×2] | 꼭짓점 (x, y), 타일 원점(x×500, y×500) 기준 m |
| | f32[nPrisms] | 높이(m) |
| | u8[nPrisms] | 외장 그룹 번호 (`manifest.facade_enum` 순서) |
| | u8[nPrisms] | 창 격자용 층수(1~255). 규칙은 `manifest.floors` |
| | 0~3 byte | 4바이트 정렬용 0 |

- 링: 프리즘의 첫 링이 외곽(반시계), 나머지가 구멍(시계). 닫는 점(첫 점 반복)은 없다
- 모든 배열이 4바이트 경계에서 시작하므로 `ArrayBuffer`를 복사 없이 `Uint32Array`·`Float32Array`로 읽는다
- 좌표 정밀도: 타일 원점 기준 float32라 수백 m 범위에서 0.1mm 이하

## manifest.json

```
format, version, region, crs, tile_size, source, created
facade_enum: ["unknown","apartment","house","commercial","office","industrial","public"]
floors: {floor_height_m: {그룹: 층고 중앙값}, overall_m, rule}   층수가 없을 때 높이 / 그룹 층고 중앙값
lods: [{lod, name, ...LOD2 기준}]
bounds: [xmin, ymin, xmax, ymax]      건물 범위
start: {x, y, tile, rule}             시작 위치 = LOD0 삼각형이 가장 많은 타일의 중심
summary: {lod: {tiles, buildings, prisms, vertices, triangles, bytes, bytes_gzip, ...}}
tiles: [{x, y, hmax, lod: [{n 건물 수, t 삼각형 수, b 바이트, gz gzip 바이트} | null] × 3}]
```

삼각형 수는 벽 2e + 지붕 (e − 2 + 2h)이다(e: 변 수, h: 구멍 수, 바닥 없음). `measure_density.py`와 같은 식이다.

## artifact 배포용 묶음 (`viewer/scripts/build-artifact.mjs`)

claude.ai artifact는 한 번에 올릴 수 있는 파일이 256개 이하라서, 타일 파일을 LOD별로 하나씩 합친다.

```
dist-artifact/tiles/<지역>/index.json     manifest.json + packs + 타일별 offset
dist-artifact/tiles/<지역>/lod<n>.bin     해당 LOD 타일 .bin을 manifest.tiles 순서로 이어 붙인 것
```

- `packs: [{lod, file, bytes, tiles}]`, 각 타일의 `lod[n]`에 `o`(offset)를 더한다. 길이는 기존 `b`
- 뷰어는 `Range: bytes=o-(o+b-1)`로 요청한다. 서버가 206을 주면 그 조각을 쓰고, 200(전체)을 주면 묶음 파일을 그 한 번만 받아 메모리에서 잘라 쓴다(첫 요청 결과를 본 뒤 나머지 요청을 보낸다)

## 뷰어의 선택 규칙 (`viewer/src/config.js`, 임시)

- 카메라 주시점(지면)에서 타일 경계까지의 최단 거리 d로 고른다: d < 500m → LOD0, < 1100m → LOD1, < 2000m → LOD2, 그 밖은 불러오지 않는다
- 먼 단계로 바꿀 때는 100m를 더 기다린다(경계 깜빡임 방지). 새 단계가 준비될 때까지 이전 단계를 보여 준다
- 거리 기준은 폰 프레임 실측 후 조정한다
