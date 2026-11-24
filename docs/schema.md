# 처리 결과 스키마

정제 결과는 데이터 출처와 무관한 계약이다. 타일 생성·뷰어는 이 스키마만 읽고 원본 칼럼(`A0`…)을 직접 참조하지 않는다. 다른 출처를 쓰더라도 같은 칼럼을 채우면 이후 단계가 그대로 동작해야 한다.

## 건물 테이블 `data/processed/buildings_<지역>.parquet`

GeoParquet, 좌표계 EPSG:5186(미터). 1행 = 원본 1건(제외된 건물도 행을 남기고 `h_src=excluded`로 표시).

| 칼럼 | 타입 | NULL | 의미 |
|---|---|---|---|
| `bldg_id` | string | 아니오 | 데이터셋 안에서 고유한 건물 id. AL_D010은 `{A23}-{A0}` |
| `geometry` | Polygon / MultiPolygon | 아니오 | 외곽선, EPSG:5186. 무효 폴리곤은 `make_valid` 후 저장하고 `h_flag`에 `geom_fixed` |
| `height_m` | float32 | 제외 건물만 | 렌더링에 쓰는 높이(m). 정제 규칙은 `data.md` |
| `h_src` | string | 아니오 | 높이 출처: `orig` 원본 / `floors` 층수 대체 / `area_default` 면적 구간 기본값 / `excluded` 렌더링 제외 |
| `h_flag` | string | 아니오(빈 문자열 허용) | 이상·주의 사유. 여러 개면 `\|`로 연결 (아래 표) |
| `facade` | string | 아니오 | 외장 패턴 그룹: `apartment` `house` `commercial` `office` `industrial` `public` `unknown` |
| `approval_year` | int16 | 예 | 사용승인연도. AL_D010은 A13의 연도 |
| `src_height` | float32 | 예 | 원본 높이 그대로(AL_D010: A16). 0·NULL 유지 |
| `src_floors` | int16 | 예 | 원본 지상층수 그대로(AL_D010: A26) |

`h_flag` 값

| 값 | 뜻 | `h_src` |
|---|---|---|
| `no_footprint` | 면적 1m² 미만 placeholder | `excluded` |
| `duplicate` | 형상이 완전히 같은 중복(첫 건만 유지) | `excluded` |
| `out_of_range` | 원본 높이가 2~600m 밖 | `floors` 또는 `area_default` |
| `ratio_low` / `ratio_high` | 2층 이상에서 높이/층수 < 2.0 / > 8.0 | `floors` |
| `single_story_tall` | 1층인데 20m 초과, 검사 대상 용도(단독·공동주택, 근린생활, 업무) | `floors` |
| `single_story_tall_kept` | 1층·20m 초과지만 검사 대상 용도가 아니라 원본 유지 | `orig` |
| `large_default` | 면적 300m² 이상인데 기본 높이 사용 | `area_default` |
| `geom_fixed` | 무효 폴리곤 보정 | 무관 |

부가 파일 `buildings_<지역>.meta.json`: 원본 파일명, 규칙 매개변수(계수·임계값), `h_src`·`h_flag`·`facade`별 건수.

## 외장 패턴 그룹 (`facade`)

매핑 원본: `scripts/facade_groups.csv`(주용도명 → 그룹). 공백·`.`·`·` 차이는 무시하고 비교하며, 매핑에 없는 값과 주용도 결측은 `unknown`.

묶는 기준은 창문 격자 shader가 구분해야 하는 외관 차이(층고, 창 비율, 매스 형태)다. 층고 근거는 세종 정제 결과에서 `h_src=orig`이고 층수가 있는 건물의 그룹별 높이/층수 중앙값(괄호는 표본 수).

| 그룹 | 포함 주용도 | 외관 특징 | 세종 층고 중앙값 |
|---|---|---|---|
| `apartment` | 공동주택 | 반복 발코니 띠, 낮은 층고, 고층 | 3.01m (375) |
| `house` | 단독주택 | 작은 창, 불규칙, 저층 | 4.00m (5,033) |
| `commercial` | 제1·2종근린생활시설, 근린생활시설(구), 판매, 숙박, 위락, 관광휴게 | 1층 상점 전면 + 상부 창 | 4.35m (2,504) |
| `office` | 업무, 방송통신 | 균일한 큰 창 격자·커튼월 | 4.70m (65) |
| `industrial` | 공장, 창고, 위험물저장, 자동차관련, 동·식물 관련(축사·온실), 분뇨·쓰레기처리(자원순환), 발전 | 창이 거의 없는 판넬 매스, 큰 층고 | 5.00m (3,976) |
| `public` | 교육연구, 노유자, 의료, 문화및집회, 종교, 운동, 수련, 운수, 교정·군사, 장례, 묘지관련, 야영장 | 규칙적인 큰 창, 중저층 | 4.39m (473) |
| `unknown` | 주용도 결측·매핑 없음 | 중립 패턴 | — |

세종은 `unknown`이 약 2/3다(대장 미연계). 중립 패턴의 품질이 화면 전체 인상을 좌우한다는 뜻이므로, 5단계에서 우선 다룬다.

## 타일 (3단계)

타일 파일 형식과 manifest는 `docs/tiles.md`.
