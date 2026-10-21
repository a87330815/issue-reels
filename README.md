# 이슈 릴스

공공데이터 기반 이슈 릴스 자동 제작·발행 파이프라인.

## 왜 이 구조인가

언론사 기사·사진은 쓰지 않는다. 보호 대상은 사실이 아니라 표현이므로,
1차 출처(정부·공공기관 보도자료, 공공데이터 API)로 올라가 사실만 뽑고 문장은 새로 쓴다.
공공누리 **제1유형**만 사용한다. 제2유형은 상업적 이용 불가, 제3유형은 변형 불가.

## 구성

| 파일 | 역할 |
|---|---|
| `sources.yml` | 수집 소스 레지스트리. 상태·인증키 환경변수·공공누리 유형·필드 매핑 |
| `collect.py` | 수집기. 게이트 3종 + 언론사 표현 필터 + 중복제거 |
| `render/cover.py` | 커버 렌더러. 커버 문법(150pt 고정, 외곽선, 포인트 컬러, 세이프존) |
| `render/render.py` | 대본 JSON → 1080x1920 릴스. 자막 번인 + TTS |
| `render/_mockbg.py` | 샘플용 가짜 배경. 운영에서는 실제 이미지로 교체 |
| `cardnews.py` | 대본 JSON → 1080x1350(4:5) 인스타 카드뉴스 PNG |
| `photos.py` | 카드 배경 사진 수집. 상업적 이용 가능 라이선스만 |
| `.github/workflows/collect.yml` | 예약 수집. `0 23 * * *` = 한국시간 08:00 |
| `.github/workflows/cards.yml` | 사진 수집 → 카드뉴스 생성 → 커밋 |
| `.github/workflows/tts_sample.yml` | 음성 품질 판정용 샘플 생성 (수동 실행) |

## 카드뉴스 배경 사진

카드마다 실사 배경을 깐다. 사진 위에 아래로 갈수록 짙어지는 그래디언트를 덮어
본문 대비를 확보하고, 본문 슬라이드는 약한 블러를 더해 글이 주인공이 되게 한다.
사진을 못 받은 슬라이드는 카테고리별 그래디언트 배경으로 자동 폴백한다.

### 수집 소스 (우선순위)

| 순위 | 소스 | 키 | 비고 |
|---|---|---|---|
| 1 | Unsplash | `UNSPLASH_ACCESS_KEY` (선택) | 적합도 최상. 무료 등록, 시간당 50건 |
| 2 | Openverse | 불필요 | CC0·PDM·CC BY만 |
| 3 | Wikimedia Commons | 불필요 | 최후 폴백 |

키를 넣지 않아도 2·3번으로 동작한다. 다만 **무료 CC 풀은 적합도가 떨어지므로**
사진 품질이 중요하면 Unsplash 키를 등록하는 쪽이 낫다
(unsplash.com/oauth/applications → Access Key → 저장소 Secrets에 `UNSPLASH_ACCESS_KEY`).

### 라이선스 정책

상업적 이용이 가능하고 2차 저작물에 조건이 전염되지 않는 것만 받는다.
**허용**: Public Domain · CC0 · PDM · CC BY
**제외**: CC BY-SA(share-alike) · NC(비상업) · ND(변경금지) · GFDL

CC BY는 표기가 조건이므로 카드 하단에 `사진 <저작자> / <출처> / <라이선스>`를 자동으로 찍는다.
표기 의무가 없는 PD·CC0는 화면을 깨끗하게 두려고 생략한다.

### 검색어

적합도는 검색어가 좌우한다. 대본 생성 단계에서 장면별 영문 `photo_query`를 함께 만들고,
없으면 `photos.py`의 한국어 키워드 매핑으로 폴백한다. 추상 개념이 아니라
"한 장의 사진으로 찍힐 장면"을 써야 한다 (`정책 혜택` ✗ → `tax documents calculator` ○).

### 진단

러너 로그와 아티팩트는 외부에서 받기 어려워, 수집 로그를 `out/photos/collect.log`로
남겨 저장소에 함께 커밋한다. 어떤 공급자가 몇 건을 줬고 무엇이 걸러졌는지 여기서 본다.

## 커버 문법

```
"이거 모르면"
"<r>1년에 7만원</r>"     ← 빨강
"그냥 날립니다"
```

`<r>` 빨강 · `<y>` 노랑. 나머지는 흰색.

**카피 제약**: 150pt 고정이라 한 줄 약 6자, 최대 4줄. 넘으면 자동 줄바꿈되고,
그래도 안 들어가면 110pt까지만 축소된다. 즉 **커버 전체 24자 이내**로 쓴다.

## 세이프존

인스타 UI에 가려지는 영역. 상단 320 / 하단 520 / 좌우 90 (1080x1920 기준).

## 사용

```bash
pip install -r requirements.txt

python collect.py --verify          # 소스 상태 점검
python collect.py                   # 수집 → out/collected.json
python render/render.py script.json -o out/reel.mp4
```

## 인증키

GitHub Actions Secrets에 등록한다. 리포지토리에 커밋하지 않는다.

- `DATA_GO_KR_KEY` — 공공데이터포털
- `KMA_APIHUB_KEY` — 기상청 API 허브
- `KOSIS_KEY` — 통계청

## 발행 시 주의

- 프로페셔널(비즈니스·크리에이터) 계정 + 페이스북 페이지 연결 필수. 개인 계정은 API 발행 불가
- 24시간 이동 기준 50건 발행 제한
- 영상을 먼저 공개 URL에 올려야 인스타가 가져간다
- **예약 시각은 UTC**. 한국시간 11시 = `02:00 UTC`

## 네트워크 제약 (2026-10-19 확인) — 설계에 영향

`apis.data.go.kr`는 **해외 IP에서 닿지 않는다.**

| 실행 위치 | 결과 |
|---|---|
| 개발 샌드박스 | 403 (허용목록 차단) |
| GitHub Actions (Azure/미국) | **ConnectTimeout** |
| 한국 IP (일반 브라우저) | 정상 응답 (`SERVICE_KEY_IS_NULL` 반환) |

즉 **수집 단계만은 한국 IP에서 실행해야 한다.** 대본 생성·영상 렌더·발행은 Actions에서 그대로 가능.
TTS(`speech.platform.bing.com`)는 반대로 Actions에서는 되고 샌드박스에서만 막힌다.

### 보안 주의
data.go.kr은 serviceKey를 **URL 쿼리에 실어 보내는** 구조라, 예외 메시지·로그에 키가 그대로 남는다.
`probe.py`의 `redact()`처럼 출력 전에 반드시 키를 지울 것. 로그·아티팩트·브랜치에 올리기 전에도 동일.

## 미해결

- 인증키 전량 미발급 → `--verify` 돌리면 전 소스 건너뜀 (설계대로)
- 데이터셋별 공공누리 유형 미확인 → `sources.yml`의 `license: unknown`을 1로 바꿔야 통과
- `field_map` 미작성 → 응답 JSON 샘플 필요
- **TTS 음성 품질 미판정** — `tts-sample` 워크플로를 수동 실행해 들어보고 결정할 것
