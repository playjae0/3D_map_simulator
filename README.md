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

프레임을 잴 때는 개발 서버(번들링 안 된 모듈, HMR 포함) 대신 빌드본을 쓴다. 주소의 포트는 4173이다.

```bash
npm run build && npm run preview:lan
```

### 조작과 화면

- 한 손가락 또는 왼쪽 드래그: 이동. 두 손가락 또는 오른쪽 드래그: 회전. 확대·축소와 기울기 변경은 없다(고정 각도)
- 이동 범위는 시작 위치(세종 조치원읍 중심부) 기준 ±3km
- 왼쪽 위: FPS(0.5초 평균)와 프레임 시간, 그린 삼각형 수, draw call 수(하늘·지면 포함), LOD별 타일 수, 받은 데이터 양

### 주소 매개변수

| 매개변수 | 기본값 | 뜻 |
|---|---|---|
| `region` | `36` | 타일 폴더(`data/processed/tiles/<region>/`) |
| `dpr` | `2` | 픽셀 비율 상한. 폰 부하 비교용으로 `?dpr=1` |
| `aa` | `1` | `?aa=0`이면 안티에일리어싱 끔 |
| `area` | `3000` | 이동 범위(시작 위치 기준 ±m) |

예: `http://192.168.0.10:5173/?dpr=1&aa=0`
