# CLAUDE.md

이 파일은 Claude Code가 이 프로젝트 작업 시 참고하는 컨텍스트 문서입니다.
Claude Code는 세션 시작 시 이 파일을 자동으로 읽습니다.

---

## 프로젝트 개요

**이름**: 한국 주식 이평선 돌파 스크리너 + 가치지표 분석기

**목적**:
1. 코스피/코스닥 전체 종목 중 일봉 종가가 N일 이동평균선을 돌파한 종목을 자동 탐지
2. 검색된 종목에 대해 가치 지표(ROE, PER, PBR, PEG, FCF) + 동종업계 평균 비교
3. 증권사 목표가 컨센서스 표시

**왜 만들었나**: HDC, LS, GS글로벌 차트에서 보이는 패턴 — 장기 이동평균선(주로 300일선) 돌파 후 상승 추세 전환 — 을 자동 탐지하고, 펀더멘털 관점에서도 검증할 수 있도록.

**핵심 가치**:
- API 키 불필요 (또는 무료 API만 사용)
- 무료 운영 (Streamlit Community Cloud 배포)
- 코딩 비전공자도 조건 변경/사용 가능한 UI

---

## 기술 스택

| 영역 | 선택 | 이유 |
|------|------|------|
| 언어 | Python 3.10+ | 데이터 분석 라이브러리 풍부 |
| 프레임워크 | Streamlit | 코드 적게 쓰고 웹 UI 자동 생성 |
| 시세 데이터 | pykrx | API 키 없음, 무료, 한국거래소 공식 |
| 종목 메타데이터 | FinanceDataReader | 종목 리스트, 업종 분류 |
| 재무 지표 | pykrx (`get_market_fundamental`) | PER/PBR/EPS/BPS/DIV/DPS |
| 컨센서스 (목표가) | 네이버 증권 크롤링 (개인용) / 미표시 (공개 배포) | 무료, 단 약관 회색지대 |
| 동종업계 평균 | 직접 계산 (KRX 업종분류 기준) | 합법, 무료 |
| 배포 | Streamlit Community Cloud | 무료, GitHub 연동 자동 배포 |

**의존성 추가 시 주의**:
- Streamlit Cloud 무료 플랜 메모리 1GB 제한
- 크롤링 라이브러리(`requests`, `beautifulsoup4`)는 OK
- Selenium 등 브라우저 자동화는 ❌ (Streamlit Cloud에서 안 됨)

---

## 프로젝트 구조 (목표)

```
stock-screener/
├── app.py                  # 메인 Streamlit 앱 (UI/메인 로직)
├── screener.py             # 이평선 돌파 스크리닝 로직
├── valuation.py            # 가치 지표 + 동종업계 평균 계산
├── consensus.py            # 증권사 목표가 수집 (크롤링)
├── data_loader.py          # pykrx/FDR 래퍼 (캐싱 포함)
├── utils.py                # 보조 함수 (포맷팅 등)
├── requirements.txt        # Python 의존성
├── README.md              # 사용자용 가이드 (한글)
├── CLAUDE.md              # 이 파일
├── .gitignore
└── .streamlit/
    └── config.toml
```

**현재 상태**: 단일 `app.py` (v0.1)
**다음 리팩토링 시점**: v0.2에서 가치지표 추가 시 `valuation.py` 분리

---

## 주요 기능 명세

### F1. 이평선 돌파 스크리닝 (구현됨)
- 입력: 시장(KOSPI/KOSDAQ), MA 기간(20/60/100/200/300), 돌파 시점, 거래량/가격 필터
- 출력: 돌파 종목 리스트 + 등락률, 이평대비%, 거래량

### F2. 시장 구분 표시 (요구사항)
- **결과 테이블에 KOSPI / KOSDAQ 컬럼 명확히 표시**
- 시장별로 결과 그룹핑하거나 탭으로 분리하는 옵션 제공
- 사용자가 한 시장만 보고 싶을 때 필터링 가능

### F3. 가치 지표 표시 (신규 - v0.2)
검색 결과 종목 클릭/선택 시 아래 정보 카드 표시:

```
[종목명]
목표가: 150,000원 (+19%)  ← iM증권, 2026/05/07 등 출처
가치 지표 (괄호는 업종평균)
  ROE  ↑   8.58%   (16.6%)
  PER  ↓   8.97    (12.8)
  PBR  ↓   0.77    (0.53)
  PEG  ↓   1.53    (0.65)
  FCF  ↑   1502    (2453)
[업계 대비 PER 우수]  ← 자동 태깅
```

**구현 세부사항**:
- ROE, PER, PBR: pykrx `get_market_fundamental()` 으로 수집
- PEG: 직접 계산 (PER ÷ EPS 성장률) — EPS는 DART 공시 데이터 필요
- FCF (잉여현금흐름): DART 공시에서 추출
- **업종평균**: KRX 업종 분류 → 같은 업종 내 종목들의 중앙값(median) 사용 (평균은 outlier에 취약)

**자동 태깅 로직**:
- ROE > 업종평균 × 1.2 → "수익성 우수"
- PER < 업종평균 × 0.8 → "업계 대비 PER 우수" (저평가)
- PBR < 업종평균 × 0.8 → "자산가치 대비 저평가"
- PEG < 1.0 → "성장 대비 저평가"

### F4. 증권사 목표가 컨센서스 (신규 - v0.2)
- **공개 배포 버전**: 사용자에게 "외부 링크에서 확인" 안내 + 네이버 증권 링크 제공
- **로컬 개인 사용 버전**: 네이버 증권 크롤링으로 자동 수집
  - URL 패턴: `https://finance.naver.com/item/main.naver?code={종목코드}`
  - 추출 항목: 평균 목표주가, 의견 종합, 목표가 제시 증권사 수, 최신 보고서 일자
  - **요청 간격**: 종목당 최소 2초 (서버 부하 방지)
  - **User-Agent 설정 필수**, robots.txt 준수
- 환경변수 `ENABLE_CONSENSUS_CRAWL=true` 일 때만 활성화

---

## 개발 원칙

### 코드 스타일
- PEP 8 준수, 함수/변수명 영어, 주석/문서/UI는 한글
- 함수마다 docstring 필수
- 타입 힌트 권장
- 매직 넘버는 상수로 추출 (`DEFAULT_MA_PERIOD = 300`)

### 기능 추가 원칙
1. **사용자 입장 우선**: 새 기능은 사이드바 옵션, 기본값은 보수적
2. **하위 호환**: 기존 워크플로우 유지
3. **느린 작업은 진행률 표시**: `st.progress`, `st.status`
4. **캐싱 적극 활용**: `@st.cache_data(ttl=...)` — 특히 크롤링 결과는 길게 (24시간+)
5. **에러 처리**: 한 종목 실패해도 전체 작업 계속 (`try/except continue`)

### 데이터 소스별 캐싱 전략
| 데이터 | TTL | 이유 |
|--------|-----|------|
| 종목 리스트 | 24시간 | 신규 상장/상폐 드뭄 |
| 일봉 OHLCV | 1시간 | 장중 갱신 가능 |
| 가치 지표 (PER/PBR) | 6시간 | 일 1회 갱신 충분 |
| 업종평균 | 24시간 | 자주 안 변함 |
| 증권사 목표가 | 24시간 | 매일 새 리포트 가능 |
| 재무제표 (DART) | 7일 | 분기 단위 갱신 |

### 성능 고려사항
- pykrx 직렬 호출은 느림 → `concurrent.futures.ThreadPoolExecutor` 활용 (rate limit 주의: max_workers=5 정도)
- 전체 종목 가치 지표는 한 번에 불러오기: `pykrx.stock.get_market_fundamental(date, market='ALL')` 사용
- 크롤링은 절대 병렬화 ❌ (서버 부담 + 차단 위험)
- 결과를 SQLite/Parquet 캐시 (당일 데이터만 갱신)

### 데이터 정합성
- 영업일 처리: 주말/공휴일 빈 데이터 가능
- 신규 상장주: 데이터 길이가 MA 기간보다 짧을 수 있음
- 거래정지/관리종목: 별도 필터 필요할 수 있음
- **업종 분류 일관성**: KRX 표준 산업분류 사용 (네이버/FnGuide와 다를 수 있음)
- 우선주/리츠/스팩: 기본 제외 (사용자 옵션으로 포함 가능)

---

## 배포 워크플로우

### 로컬 → GitHub → Streamlit Cloud 자동 배포

1. **로컬 개발**:
   ```bash
   streamlit run app.py
   ```

2. **변경사항 커밋**:
   ```bash
   git add .
   git commit -m "feat: 가치 지표 카드 추가"
   git push
   ```

3. **자동 배포**: GitHub push → Streamlit Cloud 1~2분 내 재배포

### 환경변수 관리 (Streamlit Cloud)
공개 배포 시 민감/위험 기능은 환경변수로 ON/OFF:
```toml
# .streamlit/secrets.toml (GitHub에 올리지 말 것!)
ENABLE_CONSENSUS_CRAWL = false  # 공개 배포는 false
USER_AGENT = "Mozilla/5.0 ..."
```

코드에서:
```python
import streamlit as st
ENABLE_CRAWL = st.secrets.get("ENABLE_CONSENSUS_CRAWL", False)
```

### 커밋 메시지 컨벤션 (Conventional Commits)
- `feat:` 새 기능
- `fix:` 버그 수정
- `perf:` 성능 개선
- `refactor:` 리팩토링
- `docs:` 문서 변경
- `chore:` 잡일

### 브랜치 전략
- `main`: 배포되는 안정 버전
- 큰 기능은 `feature/기능명` 브랜치 작업 후 머지
- 작은 수정은 main 직접 커밋 OK

---

## 개발 시 유의사항 (Claude Code에게)

### 새 기능 추가 요청 받았을 때
1. 사이드바 UI에 옵션 추가 (사용자가 끌 수 있게)
2. 기본값은 OFF 또는 보수적 값
3. README.md 가이드 섹션 업데이트
4. 이 CLAUDE.md "구현된 기능" / "로드맵" 섹션 업데이트
5. 커밋 메시지에 변경 의도 명확히

### 크롤링 코드 작성 시 (특히 중요)
- ✅ User-Agent 헤더 설정
- ✅ 요청 간격 최소 1~2초 (`time.sleep`)
- ✅ try/except로 차단/오류 우아하게 처리
- ✅ 캐싱 (`@st.cache_data(ttl=86400)`) 으로 중복 요청 최소화
- ✅ robots.txt 확인
- ❌ 동시 요청 / 병렬화 금지
- ❌ 자동 재시도 무한반복 금지 (max 3회)
- 코드 상단에 출처와 약관 주의 코멘트 명시

### 코드 수정 시
- `git status` / `git diff` 로 현재 상태 확인
- 큰 변경은 별도 브랜치
- 로컬에서 `streamlit run app.py` 한 번 돌려본 후 push
- requirements.txt 수정 시 버전 명시

### 디버깅 시
- pykrx 에러 → KRX 서버 점검 시간(주말 새벽) 가능성
- Streamlit 캐시 꼬임 → `st.cache_data.clear()` 또는 앱 재시작
- 종목 데이터 누락 → 신규상장/상장폐지/거래정지 확인
- 크롤링 차단 → User-Agent 변경, 요청 간격 늘리기

### 하지 말아야 할 것
- ❌ API 키 필요한 유료 서비스 도입 (FnGuide, WiseFn 등)
- ❌ 사용자 개인정보/계좌 연동
- ❌ 매수 추천 / 투자자문 표현 ("매수 추천", "강력 매수" 등 금지)
- ❌ 크롤링 병렬화 / 무차별 요청
- ❌ requirements.txt 버전 미명시
- ❌ secrets.toml 을 GitHub에 커밋

### 면책 문구 필수 표시
모든 화면 하단에 다음 문구:
> ⚠️ 본 도구는 정보 제공 목적이며, 투자 판단의 결과는 사용자 본인에게 있습니다. 데이터의 정확성을 보장하지 않습니다.

---

## 구현된 기능 (현재 v0.1)

- [x] 코스피/코스닥 시장 선택
- [x] 이동평균선 기간 선택 (20/60/100/200/300일)
- [x] 돌파 시점 필터 (최근 N일 이내)
- [x] 최소 거래량 / 주가 필터
- [x] 결과 정렬 (등락률 기준)
- [x] CSV 다운로드
- [x] 진행률 표시
- [x] 1시간 캐싱

## 로드맵

### v0.2 - 가치 지표 + 시장 구분 (다음 작업)
- [ ] 결과 테이블 시장별(KOSPI/KOSDAQ) 탭 분리
- [ ] 종목 선택 시 가치 지표 카드 표시
  - [ ] ROE, PER, PBR (pykrx fundamental)
  - [ ] 동종업계 평균 (KRX 업종분류 + 중앙값)
  - [ ] PEG (EPS 성장률 계산)
  - [ ] FCF (DART 공시)
- [ ] 자동 태깅 ("업계 대비 PER 우수" 등)
- [ ] 증권사 목표가 표시 (개인용은 크롤링, 공개용은 외부 링크)
- [ ] 가치 지표 기반 추가 필터 (PER < N, ROE > N% 등)

### v0.3 - 시각화
- [ ] 종목 클릭 시 캔들 차트 (plotly/mplfinance)
- [ ] 결과 테이블에 미니 스파크라인
- [ ] 다크모드 토글

### v0.4 - 추가 지표
- [ ] 거래량 급증 필터
- [ ] 외국인 순매수 N일 연속 필터
- [ ] RSI / MACD / 볼린저밴드
- [ ] 골든크로스 / 데드크로스 탐지
- [ ] 시가총액 범위 필터

### v0.5 - 백테스팅
- [ ] 과거 시점 기준 스크리닝
- [ ] 시그널 발생 후 N일 수익률 분석
- [ ] 전략 통계 (승률, 평균 수익률, MDD)

### v0.6 - 자동화
- [ ] 매일 장마감 후 자동 스크리닝 (GitHub Actions)
- [ ] 결과 이메일/텔레그램 발송
- [ ] 관심 종목 알림

### v1.0 - 멀티 유저
- [ ] 사용자 계정 (선택)
- [ ] 개인별 관심종목/조건 저장
- [ ] 공유 가능한 스크리닝 프리셋

---

## 자주 쓰는 명령어

### 로컬 실행
```bash
streamlit run app.py
streamlit run app.py --server.port 8502
```

### 의존성 관리
```bash
pip install -r requirements.txt
pip freeze > requirements.txt
pip install --upgrade pykrx
```

### Git
```bash
git status
git add .
git commit -m "feat: 새 기능"
git push
git log --oneline -10
```

---

## 알려진 이슈 / 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| 스크리닝 매우 느림 | pykrx 직렬 호출 | 병렬화 (max_workers=5) |
| 일부 종목 데이터 없음 | 거래정지/상폐 | try/except로 skip |
| Streamlit Cloud 메모리 초과 | 무료 플랜 1GB | 청크 처리, 캐시 TTL 단축 |
| pykrx ConnectionError | KRX 서버 일시 장애 | 재시도, 새벽 시간대 피하기 |
| 네이버 크롤링 차단 | 요청 너무 빠름 | sleep 늘리기, UA 변경 |
| 업종평균이 이상함 | outlier (적자기업 등) | 평균 대신 중앙값 사용 |

---

## 참고 자료

- pykrx 문서: https://github.com/sharebook-kr/pykrx
- pykrx fundamental: `stock.get_market_fundamental()`
- FinanceDataReader: https://github.com/financedata-org/FinanceDataReader
- DART OpenAPI: https://opendart.fss.or.kr/ (공시 데이터, 무료, API 키 무료 발급)
- KRX 업종분류: https://www.krx.co.kr
- Streamlit 문서: https://docs.streamlit.io
- Streamlit Cloud: https://docs.streamlit.io/streamlit-community-cloud

---

## 프로젝트 철학 (한 줄 요약)

> **"개미 투자자도 무료로, 코딩 없이도, 자기만의 조건으로 시장을 스캔하고 펀더멘털까지 검증할 수 있게."**

이 철학과 충돌하는 결정은 재고할 것.

### 의사결정 가이드
새 기능 도입 시 자문할 질문:
1. 사용자가 별도 비용/계정 없이 쓸 수 있나?
2. 기존 사용자의 워크플로우를 깨지 않나?
3. 데이터 소스가 합법적이고 안정적인가?
4. 투자자문 규제 위반 소지가 없나?
5. Streamlit Cloud 무료 플랜에서 작동하나?

5개 모두 YES여야 진행.
