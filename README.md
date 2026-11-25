# 3d-map-simulator

건물 외곽선과 높이로 도시를 LOD1 3D로 보여 주는 프로젝트. 결정과 근거는 `docs/`, 작업 규칙은 `CLAUDE.md`.

## 1. 데이터 처리 (Python 3.11+)

원본 SHP zip을 `data/raw/`에 둔다(예: `AL_D010_36_20261109.zip`).

```bash
python -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

```bash
.venv/bin/python scripts/refine.py data/raw/AL_D010_36_20261109.zip
```

```bash
.venv/bin/python scripts/tile.py data/processed/buildings_36.parquet
```

- `refine.py` → `data/processed/buildings_36.parquet` (+ `.meta.json`, 스키마는 `docs/schema.md`)
- `tile.py` → `data/processed/tiles/36/` (형식은 `docs/tiles.md`)
- 점검·측정: `scripts/inspect_data.py`, `scripts/measure_density.py`

### 구 하나 잘라내기 (서울 원본 → 송파구)

서울 전체 파일(약 140MB)은 테스트에 크므로, 원천 시군구코드(A23)로 구 하나만 잘라 같은 형식의 SHP zip을 만든다.

```bash
python scripts/clip_region.py data/raw/AL_D010_11_20261109.zip 11710
```

- 결과: `data/raw/AL_D010_11710_20261109.zip`(송파구). zip 안 파일 이름도 같게 바뀐다
- 원본 레코드 바이트를 그대로 골라 담으므로 필드 정의·인코딩(.cpg)·좌표계(.prj)가 원본과 같다. 바뀌는 것은 SHP 레코드 번호, 헤더의 파일 길이·범위, DBF 레코드 수뿐이다
- zip 안 파일을 처음부터 한 번씩 순서대로 읽으므로 메모리를 거의 쓰지 않는다. 실행 시간은 DBF 크기에 비례한다
- 세종 원본(12.4MB, 77,352건)으로 확인한 결과: 시군구 하나(36110, 전체)를 자르면 10.2MB·2.4초가 걸렸다. A6=2(산, 2,527건)로 자르면 0.29MB였다. 두 경우 모두 geopandas로 직접 필터한 결과와 필드·속성·형상이 같았다
- 송파구 결과 크기는 확인하지 못했다. 세종 비율(1,000건당 약 0.13MB)로 보면 건물 수가 2만~4만 건일 때 약 3~5MB로 추정한다
- 다른 필드로 자를 때: `--field A6`, 결과 경로 지정: `--out 경로.zip`

### 지역 하나를 한 번에 처리

```bash
python scripts/build_region.py data/raw/AL_D010_11710_20261109.zip --inspect
```

- 순서: (`--inspect`이면 1단계 점검) → 정제 → 타일·LOD → 미니맵 개요 이미지(`overview.png`)·법정동 라벨(manifest)
- 결과 폴더 이름은 파일 이름의 지역 코드다(`data/processed/tiles/11710/`)

## 2. 뷰어 (Node 20.19+ 또는 22.12+)

뷰어는 `data/processed/tiles/`를 정적 파일로 그대로 제공하므로, 위 1번을 먼저 실행해야 한다.

```bash
cd viewer && npm install
```

PC에서만 볼 때:

```bash
npm run dev
```

### 같은 와이파이의 폰에서 열기

1. PC와 폰을 같은 와이파이에 연결한다. 게스트 와이파이나 기기 간 통신을 막는 공유기(AP 격리)에서는 접속되지 않는다
2. `viewer/`에서 LAN에 열어 둔 개발 서버를 실행한다

   ```bash
   npm run dev:lan
   ```

3. 터미널에 나오는 `Network: http://192.168.x.x:5173/` 주소를 폰 브라우저에 입력한다. 주소가 안 보이면 PC의 IP를 직접 확인한다(Windows `ipconfig`, macOS `ipconfig getifaddr en0`, Linux `hostname -I`)
4. 접속이 안 되면 PC 방화벽에서 5173 포트(또는 Node.js)의 사설 네트워크 수신을 허용한다

### 폰 프레임 측정 절차

개발 서버(번들링 안 된 모듈, HMR 포함) 대신 빌드본을 쓴다. 주소의 포트는 4173이다.

```bash
npm run build && npm run preview:lan
```

1. 폰을 충전기에서 분리하고, 저전력 모드를 끄고, 다른 앱을 닫는다
2. 아래 조합마다 주소를 열고 왼쪽 위 `대기 0`이 될 때까지 기다린 뒤, 손대지 않고 10초 동안 FPS를 2~3번 읽어 적는다. 이어서 같은 경로(예: 한 손가락으로 위로 5번 끌기, 두 손가락으로 반 바퀴 돌리기)로 움직이며 가장 낮은 FPS를 적는다
3. 조합 사이에는 탭을 닫고 새로 연다(이전 조합의 GPU 메모리가 남지 않게)

| 순서 | 주소 뒤에 붙일 것 | 보는 것 |
|---|---|---|
| 1 | `?facade=0&ground=0` | 기준(면 음영·안개·하늘만) |
| 2 | `?facade=0&ground=1` | 접지 그늘 비용 |
| 3 | `?facade=1&ground=0` | 외장 패턴 비용 |
| 4 | `?facade=1&ground=1` | 기본 화면 |
| 5 | `?facade=1&ground=1&dpr=1` | 픽셀 수 영향(기기 픽셀 비율이 2 이상일 때) |
| 6 | `?facade=1&ground=1&aa=0` | 안티에일리어싱 비용 |

- 기록할 것: 기기·브라우저, 화면 방향, 조합별 정지 FPS와 이동 중 최저 FPS, 표시된 삼각형·draw call 수
- 쿼리 문자열을 쓸 수 없는 환경(artifact)에서는 오른쪽 위 `설정` 패널로 같은 조합을 바꾼다. 패널 값은 브라우저에 저장되고, 주소의 매개변수가 있으면 그쪽이 우선한다
- 외장 패턴을 꺼도 정점 속성(aWall)은 만들어 올린다. 그래서 1번과 3번의 차이는 셰이더 비용만 반영하고, 메모리 차이는 반영하지 않는다

### 조작과 화면

- 한 손가락 또는 왼쪽 드래그: 이동. 두 손가락 벌리기·오므리기 또는 마우스 휠: 확대·축소. 두 손가락 끌기 또는 오른쪽 드래그: 회전
- 줌: 카메라 높이 150~1,500m. 높이 400m까지는 앙각 22°(하늘이 보임), 그 위로는 1,500m에서 60°까지 점점 내려다본다. 시작은 높이 318m(v0.2 화면과 같음). 기울기는 따로 바꿀 수 없다
- 이동 범위: 데이터 범위 전체. 시작 위치는 원래 외곽선 삼각형이 가장 많은 500m 타일의 중심이다
- 오른쪽 아래 미니맵: 전체 범위의 건물 개요(밝을수록 높음, 노란색 60m 이상), 노란 사다리꼴 = 현재 시야, 빨간 점 = 주시점. 누르면 그 위치로 이동한다
- 법정동(리) 라벨: 카메라 높이 약 500m부터 나타나 600m 이상에서 다 보인다. 겹치면 건물이 많은 동을 남긴다
- 왼쪽 위: FPS(0.5초 평균)와 프레임 시간, 그린 삼각형 수, draw call 수(하늘·지면 포함), LOD별 타일 수, 받은 데이터 양(실제 전송량과 타일 크기 합계), 현재 설정
- 오른쪽 위 `설정`: 픽셀 비율 상한, 안티에일리어싱, 외장 패턴, 접지 그늘
- 오른쪽 아래: 데이터 출처 표시

### 주소 매개변수

| 매개변수 | 기본값 | 뜻 |
|---|---|---|
| `region` | `36` | 타일 폴더(`data/processed/tiles/<region>/`). 송파구는 `?region=11710`. 기본값은 `VITE_REGION=11710 npm run dev`로도 바꿀 수 있다 |
| `dpr` | `2` | 픽셀 비율 상한. 폰 부하 비교용으로 `?dpr=1` |
| `aa` | `1` | `?aa=0`이면 안티에일리어싱 끔 |
| `area` | 없음(전체) | 이동 범위를 시작 위치 기준 ±m로 제한 |
| `facade` | `1` | `?facade=0`이면 외장 창 격자 끔(단색) |
| `ground` | `1` | `?ground=0`이면 접지 그늘 끔 |

예: `http://192.168.0.10:4173/?dpr=1&aa=0&facade=0`

## 3. artifact(claude.ai 호스팅 웹페이지) 배포 빌드

```bash
cd viewer && npm run build:artifact
```

- 다른 지역: `REGION=11710 npm run build:artifact` (지역이 빌드에 들어간다. artifact는 쿼리 문자열이 없음)

- 결과: `viewer/dist-artifact/` (git에 포함). 세종 기준 파일 7개, 약 12.3MB: `index.html`, JS 2개(본체·Worker), `tiles/36/index.json`, `tiles/36/lod0~2.b64.txt`
- artifact는 임의 바이너리 파일을 제공하지 않으므로 묶음은 base64 텍스트다. 빌드 끝에 파일 형식도 검사한다
- 게시본: https://claude.ai/artifact/J1taSE7AVDofRJgzSLbNMm (비공개, 소유자만 열 수 있음)
- 타일은 LOD별 묶음 파일과 색인(index.json)으로 합친다(형식은 `docs/tiles.md`). 파일 수 256개 이하, 상대 경로만 쓰고 외부 주소를 부르지 않는지 빌드 끝에 검사한다
- 로컬 확인:

```bash
npm run preview:artifact
```

## 데이터 출처

건물 데이터: 국토교통부 GIS건물통합정보 (공공누리 제1유형, 출처표시). 뷰어 화면 오른쪽 아래에 같은 문구를 표시한다. 이용허락 조건은 공공데이터포털 안내 기준이며, 다운로드 파일에는 라이선스 문서가 없었다(`docs/data.md`).
