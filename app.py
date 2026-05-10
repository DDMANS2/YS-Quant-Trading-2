"""
YS Quant Trading — 한국 주식 이평선 돌파 스크리너 + 가치 지표 + 상세 차트
- 코스피/코스닥 시가총액 상위 N개 또는 전체
- 일봉 종가 기준 N일 이동평균선 돌파 종목 검색
- 검색 결과에 PER/PBR/ROE/PEG + 증권사 평균 목표가 + 컨센서스 일자 표시
- 종목 선택 시 캔들 차트 + 이동평균선 + 볼린저밴드 + 거래량 + MACD + RSI
- API 키 불필요 (pykrx, FinanceDataReader, 네이버 모바일 stock JSON)
"""

import concurrent.futures
import re
import time
from datetime import datetime, timedelta

# pykrx의 get_market_ohlcv는 내부적으로 fchart.stock.naver.com 차트 API를 호출하는데,
# 짧은 시간에 100건+ 요청하면 네이버가 IP rate limit을 걸어 무한 대기가 발생한다.
# requests의 HTTPAdapter.send에 timeout을 강제 주입해 응답 없는 요청을 끊어내고
# 워커를 풀어준다. (socket.setdefaulttimeout으로는 requests의 connection pool에 적용되지 않는다.)
REQUEST_TIMEOUT_SEC = 8
import requests  # noqa: E402
import requests.adapters as _requests_adapters  # noqa: E402

_orig_adapter_send = _requests_adapters.HTTPAdapter.send


def _adapter_send_with_timeout(self, request, **kwargs):
    if kwargs.get("timeout") is None:
        kwargs["timeout"] = REQUEST_TIMEOUT_SEC
    return _orig_adapter_send(self, request, **kwargs)


_requests_adapters.HTTPAdapter.send = _adapter_send_with_timeout

import FinanceDataReader as fdr  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402
from plotly.subplots import make_subplots  # noqa: E402
from pykrx import stock  # noqa: E402

# 병렬 호출 동시성: 네이버 fchart의 IP rate limit 회피를 위해 보수적으로 5
MAX_WORKERS = 5
# OHLCV timeout 시 1회 재시도
RETRY_COUNT = 1
# 가치 지표 fetch 시 동시성은 더 보수적으로 (네이버 모바일 API 보호)
VALUATION_WORKERS = 3

NAVER_UA = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)"}

# ============================================================
# 페이지 설정 / 스타일
# ============================================================
st.set_page_config(
    page_title="YS Quant Trading",
    page_icon="📈",
    layout="wide",
)

st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
    :root {
        --bg: #ffffff;
        --surface: #fafafa;
        --surface-2: #f4f4f5;
        --border: #e5e7eb;
        --border-strong: #d4d4d8;
        --text: #0f172a;
        --text-muted: #64748b;
        --text-subtle: #94a3b8;
        --accent: #0f172a;
        --up: #dc2626;
        --down: #2563eb;
        --flat: #6b7280;
        --radius-sm: 8px;
        --radius: 12px;
        --radius-lg: 16px;
        --shadow-sm: 0 1px 2px rgba(15,23,42,0.04);
        --shadow: 0 4px 16px rgba(15,23,42,0.06);
        --font-display: "Pretendard", "Inter", -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
        --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
    }

    /* 전역 타이포그래피 - 한글 + 영문 균형 */
    html, body, [class*="css"] {
        font-family: var(--font-display) !important;
        color: var(--text) !important;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }
    .main .block-container {
        padding-top: 2.0rem;
        padding-bottom: 4rem;
        max-width: 1280px;
    }

    /* 헤더 */
    .ys-eyebrow {
        font-family: var(--font-mono);
        font-size: 0.72rem;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--text-subtle);
        margin-bottom: 0.4rem;
    }
    .ys-title {
        font-size: clamp(2.0rem, 1.4rem + 1.6vw, 2.75rem);
        font-weight: 800;
        letter-spacing: -0.025em;
        color: var(--text);
        line-height: 1.05;
        margin: 0;
    }
    .ys-title em {
        font-style: normal;
        background: linear-gradient(120deg, #0f172a 0%, #475569 100%);
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .ys-subtitle {
        color: var(--text-muted);
        font-size: 0.95rem;
        line-height: 1.55;
        max-width: 720px;
        margin: 0.6rem 0 0 0;
    }
    .ys-divider {
        height: 1px;
        background: var(--border);
        border: 0;
        margin: 1.6rem 0;
    }

    /* 지수 카드 - editorial 풍 */
    .index-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 14px;
        margin-top: 1.2rem;
    }
    @media (max-width: 720px) {
        .index-grid { grid-template-columns: 1fr; }
    }
    .index-card {
        padding: 1.1rem 1.2rem 1.0rem;
        border: 1px solid var(--border);
        border-radius: var(--radius);
        background: var(--bg);
        box-shadow: var(--shadow-sm);
        transition: transform 120ms ease, box-shadow 120ms ease, border-color 120ms ease;
        position: relative;
        overflow: hidden;
    }
    .index-card::before {
        content: "";
        position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
        background: var(--text-subtle);
        opacity: 0.2;
    }
    .index-card.is-up::before { background: var(--up); opacity: 0.9; }
    .index-card.is-down::before { background: var(--down); opacity: 0.9; }
    .index-card:hover {
        border-color: var(--border-strong);
        box-shadow: var(--shadow);
        transform: translateY(-1px);
    }
    .index-name {
        font-size: 0.78rem;
        color: var(--text-muted);
        font-weight: 500;
        letter-spacing: 0.02em;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .index-date {
        font-family: var(--font-mono);
        color: var(--text-subtle);
        font-size: 0.7rem;
    }
    .index-value {
        font-family: var(--font-mono);
        font-size: 1.8rem;
        font-weight: 700;
        letter-spacing: -0.02em;
        color: var(--text);
        margin-top: 0.4rem;
        line-height: 1.0;
    }
    .index-delta {
        font-family: var(--font-mono);
        font-size: 0.85rem;
        font-weight: 500;
        margin-top: 0.5rem;
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
    }
    .index-up { color: var(--up); }
    .index-down { color: var(--down); }
    .index-flat { color: var(--flat); }
    .index-arrow {
        display: inline-flex;
        width: 16px; height: 16px;
        align-items: center; justify-content: center;
        border-radius: 4px;
        font-size: 0.7rem;
    }
    .index-up .index-arrow { background: rgba(220,38,38,0.10); }
    .index-down .index-arrow { background: rgba(37,99,235,0.10); }

    /* 클릭 가능한 카드 */
    .index-card-link {
        display: block;
        text-decoration: none !important;
        color: inherit !important;
        cursor: pointer;
    }
    .index-card-link:hover {
        text-decoration: none !important;
    }
    .index-spark {
        margin-top: 0.7rem;
        margin-bottom: 0.3rem;
    }
    .index-spark-meta {
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 0.72rem;
        font-family: var(--font-mono);
    }

    /* 결과 요약 인포그래픽 (도넛 + 막대) */
    .ys-summary-grid {
        display: grid;
        grid-template-columns: 1.2fr 1fr 1fr 1fr;
        gap: 14px;
        margin: 0.8rem 0 0.4rem 0;
    }
    @media (max-width: 720px) {
        .ys-summary-grid { grid-template-columns: 1fr 1fr; }
    }
    .ys-summary {
        padding: 1.0rem 1.1rem;
        border: 1px solid var(--border);
        border-radius: var(--radius);
        background: var(--bg);
        box-shadow: var(--shadow-sm);
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        min-height: 110px;
    }
    .ys-summary-label {
        font-size: 0.72rem;
        color: var(--text-muted);
        font-weight: 500;
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }
    .ys-summary-value {
        font-family: var(--font-mono);
        font-size: 1.7rem;
        font-weight: 800;
        color: var(--text);
        letter-spacing: -0.02em;
        line-height: 1.0;
        margin-top: 0.4rem;
    }
    .ys-summary-sub {
        font-size: 0.74rem;
        color: var(--text-muted);
        margin-top: 0.4rem;
        font-family: var(--font-mono);
    }
    .ys-donut-row {
        display: flex;
        align-items: center;
        gap: 0.9rem;
    }
    .ys-donut-legend {
        display: flex;
        flex-direction: column;
        gap: 0.3rem;
        flex: 1;
    }
    .ys-donut-leg {
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 0.78rem;
    }
    .ys-donut-leg .dot {
        display: inline-block; width: 8px; height: 8px; border-radius: 999px;
        margin-right: 0.45rem; vertical-align: middle;
    }
    .ys-donut-leg .num {
        font-family: var(--font-mono);
        font-weight: 600;
        color: var(--text);
    }

    /* 진행 막대 (등락률 분포 시각화) */
    .ys-bar-track {
        height: 6px;
        background: var(--surface-2);
        border-radius: 999px;
        overflow: hidden;
        margin-top: 0.5rem;
    }
    .ys-bar-fill {
        height: 100%;
        border-radius: 999px;
        transition: width 240ms ease;
    }

    /* 사이드바 */
    section[data-testid="stSidebar"] {
        background: var(--surface);
        border-right: 1px solid var(--border);
    }
    section[data-testid="stSidebar"] .block-container {
        padding-top: 1.5rem;
    }
    section[data-testid="stSidebar"] h2 {
        font-size: 1.05rem;
        font-weight: 700;
        letter-spacing: -0.01em;
        color: var(--text);
        margin-bottom: 0.8rem;
    }
    section[data-testid="stSidebar"] label {
        font-weight: 500;
        color: var(--text);
        font-size: 0.85rem;
    }

    /* 입력 컨트롤 */
    .stSelectbox > div > div,
    .stMultiSelect > div > div,
    .stNumberInput > div > div {
        border-radius: var(--radius-sm) !important;
        border-color: var(--border) !important;
        background: var(--bg) !important;
    }
    .stSelectbox > div > div:hover,
    .stMultiSelect > div > div:hover {
        border-color: var(--border-strong) !important;
    }

    /* 슬라이더 */
    .stSlider [data-baseweb="slider"] > div > div { background: var(--text) !important; }

    /* 기본 버튼 */
    .stButton > button {
        border-radius: var(--radius-sm);
        font-weight: 600;
        letter-spacing: -0.005em;
        border: 1px solid var(--border);
        transition: all 120ms ease;
    }
    .stButton > button[kind="primary"] {
        background: var(--text);
        color: #fff;
        border-color: var(--text);
    }
    .stButton > button[kind="primary"]:hover {
        background: #1e293b;
        transform: translateY(-1px);
        box-shadow: var(--shadow);
    }

    /* 메트릭 (st.metric) */
    [data-testid="stMetric"] {
        background: var(--bg);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 0.9rem 1.0rem;
        box-shadow: var(--shadow-sm);
    }
    [data-testid="stMetricLabel"] {
        color: var(--text-muted) !important;
        font-size: 0.78rem !important;
        font-weight: 500 !important;
        letter-spacing: 0.01em;
    }
    [data-testid="stMetricValue"] {
        font-family: var(--font-mono);
        color: var(--text) !important;
        font-weight: 700 !important;
        font-size: 1.4rem !important;
        letter-spacing: -0.02em;
    }
    [data-testid="stMetricDelta"] {
        font-family: var(--font-mono);
        font-size: 0.8rem !important;
    }

    /* 데이터프레임 - 모노스페이스 숫자, 정돈된 헤더 */
    .stDataFrame {
        font-family: var(--font-display);
        font-size: 0.88rem;
        border-radius: var(--radius);
        overflow: hidden;
        border: 1px solid var(--border);
    }
    .stDataFrame thead tr th {
        background: var(--surface-2) !important;
        color: var(--text) !important;
        font-weight: 600 !important;
        font-size: 0.78rem !important;
        letter-spacing: 0.02em;
        text-transform: uppercase;
        border-bottom: 1px solid var(--border-strong) !important;
    }
    .stDataFrame tbody td {
        font-variant-numeric: tabular-nums;
    }

    /* alert/info/success/warning 박스 */
    [data-testid="stAlert"] {
        border-radius: var(--radius);
        border: 1px solid var(--border);
        background: var(--surface);
        padding: 0.85rem 1.1rem;
    }

    /* expander */
    .streamlit-expanderHeader {
        font-weight: 600;
        font-size: 0.95rem;
        color: var(--text);
        background: var(--surface);
        border-radius: var(--radius-sm);
    }

    /* 섹션 라벨 (h2/h3) */
    h2, h3 {
        font-weight: 700;
        letter-spacing: -0.02em;
        color: var(--text);
    }
    h2 { font-size: 1.4rem; margin-top: 1.4rem; }
    h3 { font-size: 1.15rem; }

    /* 캡션 */
    [data-testid="stCaptionContainer"], .stCaption {
        color: var(--text-muted) !important;
        font-size: 0.8rem !important;
    }

    /* 가치 카드 영역 */
    .ys-section-label {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        font-size: 0.78rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--text-muted);
        margin-bottom: 0.6rem;
    }
    .ys-section-label::before {
        content: "";
        width: 14px; height: 1px;
        background: var(--border-strong);
    }

    /* 푸터 */
    .ys-footer {
        text-align: center;
        color: var(--text-subtle);
        font-size: 0.78rem;
        margin-top: 3rem;
        padding-top: 1.2rem;
        border-top: 1px solid var(--border);
    }
    .ys-footer strong { color: var(--text-muted); font-weight: 600; }

    /* 종목 상세 패널 - 가치 카드 */
    .ys-stat-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 10px;
        margin-bottom: 1.2rem;
    }
    .ys-stat {
        padding: 0.8rem 0.9rem;
        border: 1px solid var(--border);
        border-radius: var(--radius-sm);
        background: var(--bg);
    }
    .ys-stat-label {
        font-size: 0.72rem;
        color: var(--text-muted);
        font-weight: 500;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }
    .ys-stat-value {
        font-family: var(--font-mono);
        font-size: 1.15rem;
        font-weight: 700;
        color: var(--text);
        margin-top: 0.2rem;
        letter-spacing: -0.02em;
    }
    .ys-stat-sub {
        font-size: 0.7rem;
        color: var(--text-subtle);
        margin-top: 0.2rem;
    }

    /* 컨센서스 박스 */
    .ys-consensus {
        padding: 1.0rem 1.1rem;
        border: 1px solid var(--border);
        border-radius: var(--radius);
        background: var(--surface);
    }
    .ys-consensus .target-price {
        font-family: var(--font-mono);
        font-size: 1.6rem;
        font-weight: 800;
        color: var(--text);
        letter-spacing: -0.02em;
    }
    .ys-consensus .upside {
        font-family: var(--font-mono);
        font-size: 0.95rem;
        margin-left: 0.5rem;
    }
    .ys-consensus .meta {
        font-size: 0.78rem;
        color: var(--text-muted);
        margin-top: 0.3rem;
    }
    .ys-pill {
        display: inline-block;
        padding: 0.18rem 0.55rem;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 600;
        background: rgba(15,23,42,0.06);
        color: var(--text);
        margin-left: 0.4rem;
    }
    .ys-pill.is-buy { background: rgba(220,38,38,0.10); color: var(--up); }
    .ys-pill.is-hold { background: rgba(107,114,128,0.12); color: var(--flat); }
    .ys-pill.is-sell { background: rgba(37,99,235,0.10); color: var(--down); }

    /* 리포트 리스트 */
    .ys-report {
        padding: 0.7rem 0.9rem;
        border: 1px solid var(--border);
        border-radius: var(--radius-sm);
        background: var(--bg);
        margin-bottom: 0.5rem;
    }
    .ys-report .meta {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 0.74rem;
        color: var(--text-muted);
        margin-bottom: 0.2rem;
    }
    .ys-report .date {
        font-family: var(--font-mono);
        color: var(--text-subtle);
    }
    .ys-report .broker {
        font-weight: 600;
        color: var(--text);
    }
    .ys-report .title {
        font-size: 0.92rem;
        color: var(--text);
        line-height: 1.4;
    }

    /* 헤더 위쪽 메뉴 / Deploy 버튼은 그대로 */
    /* Streamlit 기본 footer 숨김 */
    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }

    /* ============================================================ */
    /* 반응형 — 태블릿 / 모바일                                       */
    /* ============================================================ */

    /* 태블릿 (≤1024px): 좌우 패딩 축소, 요약 그리드 4→2열 */
    @media (max-width: 1024px) {
        .main .block-container {
            padding-left: 1.2rem;
            padding-right: 1.2rem;
            padding-top: 1.5rem;
        }
        .ys-summary-grid {
            grid-template-columns: 1fr 1fr;
        }
        .ys-title { font-size: clamp(1.8rem, 1.4rem + 1.2vw, 2.4rem); }
    }

    /* 모바일 (≤768px): 단일 컬럼 + st.columns 세로 스택 + 폰트 축소 */
    @media (max-width: 768px) {
        .main .block-container {
            padding-left: 1rem;
            padding-right: 1rem;
            padding-top: 1rem;
            padding-bottom: 2.5rem;
        }
        .ys-eyebrow { font-size: 0.62rem; letter-spacing: 0.14em; }
        .ys-title { font-size: clamp(1.6rem, 1.2rem + 2.4vw, 2.0rem); }
        .ys-subtitle { font-size: 0.86rem; }
        .ys-divider { margin: 1.2rem 0; }

        /* 카드 그리드 — 모두 단일/2열 */
        .index-grid { grid-template-columns: 1fr; gap: 10px; }
        .ys-summary-grid { grid-template-columns: 1fr 1fr; gap: 10px; }
        .ys-stat-grid { grid-template-columns: 1fr 1fr; gap: 8px; }

        /* 카드 폰트/패딩 축소 */
        .index-card { padding: 0.95rem 1.05rem 0.85rem; }
        .index-value { font-size: 1.5rem; }
        .index-spark { margin-top: 0.55rem; }
        .ys-summary { padding: 0.85rem 0.95rem; min-height: 96px; }
        .ys-summary-value { font-size: 1.35rem; }
        .ys-stat { padding: 0.65rem 0.75rem; }
        .ys-stat-value { font-size: 1.0rem; }
        .ys-consensus { padding: 0.85rem 1.0rem; }
        .ys-consensus .target-price { font-size: 1.35rem; }

        /* st.columns를 메인 영역에서 세로 스택 (사이드바는 기본 붕괴됨) */
        section.main [data-testid="stHorizontalBlock"] {
            flex-wrap: wrap !important;
            gap: 0.6rem !important;
        }
        section.main [data-testid="stHorizontalBlock"] > [data-testid="column"] {
            flex: 1 1 100% !important;
            width: 100% !important;
            min-width: 0 !important;
        }

        /* 메트릭 위젯 컴팩트 */
        [data-testid="stMetric"] { padding: 0.65rem 0.8rem; }
        [data-testid="stMetricValue"] { font-size: 1.1rem !important; }
        [data-testid="stMetricLabel"] { font-size: 0.72rem !important; }

        /* DataFrame: 가로 스크롤 + 폰트 축소 */
        .stDataFrame { font-size: 0.78rem; }
        .stDataFrame thead tr th { font-size: 0.7rem !important; }

        /* Plotly: 모바일에서 모드바 항상 표시 */
        .js-plotly-plot .modebar { opacity: 0.95 !important; }

        /* 사이드바 폭 조정 (모바일에서 펼쳤을 때) */
        section[data-testid="stSidebar"] {
            min-width: 84vw !important;
            max-width: 92vw !important;
        }

        /* 헤더 마진 컴팩트 */
        h2 { font-size: 1.2rem; margin-top: 1.0rem; }
        h3 { font-size: 1.05rem; }
    }

    /* 매우 좁은 화면 (≤480px, 모바일 세로): 모든 그리드 단일 컬럼 */
    @media (max-width: 480px) {
        .ys-summary-grid { grid-template-columns: 1fr; }
        .ys-stat-grid { grid-template-columns: 1fr; }
        .ys-title { font-size: 1.55rem; letter-spacing: -0.02em; }
        .index-value { font-size: 1.35rem; }
        .ys-summary-value { font-size: 1.25rem; }

        /* 차트 보조지표 토글이 5개 → 모바일 세로에선 줄바꿈 */
        .stCheckbox { font-size: 0.85rem; }

        /* 푸터 컴팩트 */
        .ys-footer { font-size: 0.72rem; padding-top: 0.9rem; margin-top: 2rem; }
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# 데이터: 시장 지수 (KOSPI / KOSDAQ / KOSPI200)
# ============================================================
# 네이버 증권 지수 페이지 매핑
NAVER_INDEX_URL = {
    "코스피": "https://finance.naver.com/sise/sise_index.naver?code=KOSPI",
    "코스닥": "https://finance.naver.com/sise/sise_index.naver?code=KOSDAQ",
    "코스피200": "https://finance.naver.com/sise/sise_index.naver?code=KPI200",
}


@st.cache_data(ttl=600)
def get_market_indices():
    """FinanceDataReader로 한국 주요 지수의 최신 종가/등락 + 30일 시계열 반환."""
    out = {}
    targets = [("KS11", "코스피"), ("KQ11", "코스닥"), ("KS200", "코스피200")]
    for sym, label in targets:
        try:
            df = fdr.DataReader(sym)
            if df is None or len(df) < 2:
                out[label] = None
                continue
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            close = float(latest["Close"])
            prev_close = float(prev["Close"])
            change = close - prev_close
            pct = (change / prev_close * 100) if prev_close else 0.0
            spark = [float(v) for v in df["Close"].tail(30).tolist()]
            out[label] = {
                "price": close,
                "change": change,
                "pct": pct,
                "date": df.index[-1].strftime("%Y-%m-%d"),
                "spark": spark,
                "spark_pct": (close - spark[0]) / spark[0] * 100 if spark and spark[0] else 0,
            }
        except Exception:
            out[label] = None
    return out


def donut_svg(parts, size=68, thickness=8, center_text=None, center_sub=None):
    """parts: [(value, color, label)]. 단순 SVG 도넛 (centered text 지원)."""
    total = sum(v for v, _, _ in parts) or 1
    cx, cy, r = size / 2, size / 2, (size - thickness) / 2
    import math
    circ = 2 * math.pi * r
    offset = 0
    arcs = []
    for v, color, _ in parts:
        if v <= 0:
            continue
        frac = v / total
        dash = circ * frac
        arcs.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
            f'stroke="{color}" stroke-width="{thickness}" stroke-linecap="butt" '
            f'stroke-dasharray="{dash:.2f} {circ - dash + 0.5:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" '
            f'transform="rotate(-90 {cx} {cy})"/>'
        )
        offset += dash
    text_html = ""
    if center_text:
        text_html += (
            f'<text x="{cx}" y="{cy}" text-anchor="middle" dominant-baseline="central" '
            f'font-family="JetBrains Mono, ui-monospace, monospace" font-size="14" '
            f'font-weight="700" fill="#0f172a">{center_text}</text>'
        )
    if center_sub:
        text_html += (
            f'<text x="{cx}" y="{cy + 14}" text-anchor="middle" dominant-baseline="central" '
            f'font-family="Pretendard, Inter, sans-serif" font-size="9" fill="#94a3b8">{center_sub}</text>'
        )
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" style="display:block">'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#f1f5f9" stroke-width="{thickness}"/>'
        + "".join(arcs) + text_html + "</svg>"
    )


def sparkline_svg(values, width=140, height=36, color="#0f172a", fill_alpha=0.10):
    """심플한 인라인 SVG 스파크라인 (선 + 옅은 채움 영역)."""
    if not values or len(values) < 2:
        return ""
    vmin, vmax = min(values), max(values)
    if vmax == vmin:
        vmax = vmin + 1
    n = len(values)
    pad = 2
    pts = []
    for i, v in enumerate(values):
        x = i / (n - 1) * (width - 2 * pad) + pad
        y = (height - pad) - (v - vmin) / (vmax - vmin) * (height - 2 * pad)
        pts.append((x, y))
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    # 채움 영역 path (line + bottom right + bottom left)
    area = f"M {pts[0][0]:.1f},{pts[0][1]:.1f} " + \
           " ".join(f"L {x:.1f},{y:.1f}" for x, y in pts[1:]) + \
           f" L {pts[-1][0]:.1f},{height} L {pts[0][0]:.1f},{height} Z"
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="none" style="display:block">'
        f'<path d="{area}" fill="{color}" fill-opacity="{fill_alpha}" stroke="none"/>'
        f'<polyline points="{poly}" fill="none" stroke="{color}" '
        f'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
        f'</svg>'
    )


def render_market_indices():
    """헤더 영역에 코스피/코스닥/코스피200 인포그래픽 카드 (네이버 링크)."""
    indices = get_market_indices()
    cards_html = ['<div class="index-grid">']
    for label, data in indices.items():
        href = NAVER_INDEX_URL.get(label, "#")
        if not data:
            cards_html.append(
                f'<a class="index-card index-card-link" href="{href}" target="_blank" rel="noopener">'
                f'<div class="index-name"><span>{label}</span><span class="index-date">—</span></div>'
                f'<div class="index-value">—</div>'
                f'<div class="index-delta index-flat">데이터 없음</div>'
                f'</a>'
            )
            continue
        ch = data["change"]
        pct = data["pct"]
        if ch > 0:
            klass, arrow, card_state, line_color = "index-up", "▲", "is-up", "#dc2626"
        elif ch < 0:
            klass, arrow, card_state, line_color = "index-down", "▼", "is-down", "#2563eb"
        else:
            klass, arrow, card_state, line_color = "index-flat", "·", "", "#6b7280"

        spark = sparkline_svg(data["spark"], width=140, height=36, color=line_color)
        spark30 = data.get("spark_pct", 0)
        spark30_klass = "index-up" if spark30 > 0 else ("index-down" if spark30 < 0 else "index-flat")

        cards_html.append(
            f'<a class="index-card index-card-link {card_state}" href="{href}" target="_blank" rel="noopener">'
            f'<div class="index-name">'
            f'<span>{label}</span>'
            f'<span class="index-date">{data["date"]} · 네이버 ↗</span>'
            f'</div>'
            f'<div class="index-value">{data["price"]:,.2f}</div>'
            f'<div class="index-delta {klass}">'
            f'<span class="index-arrow">{arrow}</span>'
            f'{ch:+,.2f}'
            f'<span style="color:var(--text-subtle);font-weight:400;margin-left:0.25rem">({pct:+.2f}%)</span>'
            f'</div>'
            f'<div class="index-spark">{spark}</div>'
            f'<div class="index-spark-meta">'
            f'<span style="color:var(--text-subtle)">최근 30거래일</span>'
            f'<span class="{spark30_klass}" style="font-family:var(--font-mono);font-weight:600">{spark30:+.2f}%</span>'
            f'</div>'
            f'</a>'
        )
    cards_html.append('</div>')
    st.markdown("".join(cards_html), unsafe_allow_html=True)


# ============================================================
# 데이터: 종목 리스트 (FDR + 시총 정렬)
# ============================================================
def _fetch_ticker_list_naver(market):
    """네이버 모바일 marketValue API로 시총 정렬 종목 리스트.

    한국 외 IP(예: Streamlit Cloud)에서 KRX data API가 차단된 경우의 fallback.
    네이버는 우선주/리츠/펀드까지 포함하지만 시총 상위 N으로 자르면 사실상 보통주 위주.
    """
    rows = []
    rank = 0
    for page in range(1, 50):  # 안전 한도 (max 5000개)
        try:
            r = requests.get(
                f"https://m.stock.naver.com/api/stocks/marketValue/{market}",
                params={"page": page, "pageSize": 100},
                headers=NAVER_UA, timeout=10,
            )
            if not r.ok:
                break
            data = r.json()
        except Exception:
            break
        stocks = data.get("stocks") or []
        if not stocks:
            break
        for s in stocks:
            rank += 1
            marcap_raw = s.get("marketValueRaw") or s.get("marketValue") or "0"
            if isinstance(marcap_raw, str):
                marcap_raw = marcap_raw.replace(",", "")
            try:
                marcap_int = int(float(marcap_raw))
            except (ValueError, TypeError):
                marcap_int = 0
            rows.append({
                "code": str(s.get("itemCode", "")).zfill(6),
                "name": s.get("stockName", ""),
                "market": market,
                "marcap": marcap_int,
                "rank": rank,
            })
        total = data.get("totalCount", 0)
        if rank >= total or len(stocks) < 100:
            break
    return rows


def _fetch_ticker_list_fdr(market):
    """FinanceDataReader로 종목 리스트 (한국 IP에서 빠름)."""
    df = fdr.StockListing(market)
    if df is None or len(df) == 0:
        return []
    if "Marcap" in df.columns:
        df = df.sort_values("Marcap", ascending=False, na_position="last").reset_index(drop=True)
    df = df.copy()
    df["_rank"] = range(1, len(df) + 1)
    rows = []
    for _, r in df.iterrows():
        marcap = r.get("Marcap")
        rows.append({
            "code": str(r["Code"]).zfill(6),
            "name": r.get("Name", ""),
            "market": market,
            "marcap": int(marcap) if pd.notna(marcap) else 0,
            "rank": int(r["_rank"]),
        })
    return rows


@st.cache_data(ttl=3600)
def get_ticker_list(markets, top_n_per_market=None):
    """종목 리스트 + 시가총액 상위 N개 필터링.

    1차 시도: FinanceDataReader (KRX data API — 한국 IP에서 빠름)
    2차 fallback: 네이버 모바일 stock JSON (Streamlit Cloud 등 한국 외 IP에서 안정)
    """
    top_n_per_market = top_n_per_market or {}
    rows = []
    for m in markets:
        market_rows = []
        fdr_err = None
        try:
            market_rows = _fetch_ticker_list_fdr(m)
        except Exception as e:
            fdr_err = e

        if not market_rows:
            try:
                market_rows = _fetch_ticker_list_naver(m)
                if market_rows:
                    st.info(
                        f"ℹ️ {m}: FinanceDataReader 실패로 네이버 데이터로 대체했습니다 "
                        f"(시가총액 상위 정렬, {len(market_rows)}개)."
                    )
            except Exception as e:
                st.warning(f"{m} 종목 리스트 로딩 실패: FDR={fdr_err} / Naver={e}")
                continue

        if not market_rows:
            st.warning(f"{m} 종목 리스트가 비어 있습니다.")
            continue

        limit = top_n_per_market.get(m)
        if limit:
            market_rows = market_rows[:limit]
        rows.extend(market_rows)

    return pd.DataFrame(rows)


# ============================================================
# 데이터: 일봉 OHLCV (pykrx, retry/timeout 포함)
# ============================================================
def _fetch_ohlcv_with_retry(code, start_str, end_str, retries=RETRY_COUNT):
    """OHLCV 호출에 timeout/네트워크 오류 시 백오프 후 재시도."""
    for attempt in range(retries + 1):
        try:
            return stock.get_market_ohlcv(start_str, end_str, code)
        except Exception:
            if attempt < retries:
                time.sleep(0.5 + 0.5 * attempt)
            else:
                return None
    return None


# ============================================================
# 데이터: 네이버 모바일 stock JSON (펀더멘털 + 컨센서스 + 리서치)
# ============================================================
def _to_float(text):
    """'40.90배', '6,564원', '0.62%' 같은 문자열에서 첫 숫자만 float으로."""
    if text is None:
        return None
    s = str(text).replace(",", "").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _parse_int(text):
    if text is None:
        return None
    s = str(text).replace(",", "").strip()
    m = re.search(r"-?\d+", s)
    return int(m.group()) if m else None


@st.cache_data(ttl=86400)
def fetch_naver_valuation(code):
    """네이버 모바일 stock API에서 종목 펀더멘털 + 목표가 + ROE + 리서치를 가져온다.

    실패 시 빈 dict 반환. 캐시 24시간 (네이버 부하 최소화).
    """
    out = {"code": code}
    # 1) integration: PER/PBR/EPS/BPS/추정PER/배당, consensusInfo, researches
    try:
        r = requests.get(
            f"https://m.stock.naver.com/api/stock/{code}/integration",
            headers=NAVER_UA, timeout=8,
        )
        if r.ok:
            d = r.json()
            ti_map = {it.get("code"): it for it in (d.get("totalInfos") or [])}
            out["per"] = _to_float(ti_map.get("per", {}).get("value"))
            out["per_desc"] = ti_map.get("per", {}).get("valueDesc")
            out["pbr"] = _to_float(ti_map.get("pbr", {}).get("value"))
            out["pbr_desc"] = ti_map.get("pbr", {}).get("valueDesc")
            out["eps"] = _parse_int(ti_map.get("eps", {}).get("value"))
            out["bps"] = _parse_int(ti_map.get("bps", {}).get("value"))
            out["cns_per"] = _to_float(ti_map.get("cnsPer", {}).get("value"))
            out["cns_eps"] = _parse_int(ti_map.get("cnsEps", {}).get("value"))
            out["dividend_yield"] = _to_float(ti_map.get("dividendYieldRatio", {}).get("value"))

            cons = d.get("consensusInfo") or {}
            out["target_price"] = _parse_int(cons.get("priceTargetMean"))
            out["target_recomm"] = _to_float(cons.get("recommMean"))
            out["target_date"] = cons.get("createDate")

            researches = d.get("researches") or []
            out["researches"] = [
                {
                    "broker": r_.get("bnm"),
                    "title": r_.get("tit"),
                    "date": r_.get("wdt"),
                }
                for r_ in researches[:5]
            ]
    except Exception:
        pass

    # 2) finance/annual: ROE 시계열 + EPS 시계열 (PEG 자체 계산용)
    try:
        r = requests.get(
            f"https://m.stock.naver.com/api/stock/{code}/finance/annual",
            headers=NAVER_UA, timeout=8,
        )
        if r.ok:
            d = r.json()
            fin = d.get("financeInfo") or {}
            titles = fin.get("trTitleList") or []  # [{title, key, isConsensus}]
            rows = fin.get("rowList") or []
            row_by_title = {row.get("title"): row for row in rows}

            # 가장 최근 실적 연도(컨센서스 아닌) 키
            actual_keys = [t["key"] for t in titles if t.get("isConsensus") != "Y"]
            if actual_keys:
                last_key = actual_keys[-1]  # 가장 최근 실적 (예: 202512)
                prev_key = actual_keys[-2] if len(actual_keys) >= 2 else None

                roe_row = row_by_title.get("ROE")
                if roe_row:
                    cell = (roe_row.get("columns") or {}).get(last_key, {})
                    out["roe"] = _to_float(cell.get("value"))
                    out["roe_year"] = last_key

                # PEG = PER / EPS 성장률 (직접 계산)
                eps_row = row_by_title.get("EPS")
                per = out.get("per")
                if eps_row and prev_key and per is not None:
                    cur = _to_float((eps_row.get("columns") or {}).get(last_key, {}).get("value"))
                    pre = _to_float((eps_row.get("columns") or {}).get(prev_key, {}).get("value"))
                    if cur and pre and pre > 0 and cur > 0:
                        growth_pct = (cur - pre) / pre * 100
                        if growth_pct > 0:
                            out["peg"] = round(per / growth_pct, 2)
                            out["eps_growth_pct"] = round(growth_pct, 2)
    except Exception:
        pass

    return out


def render_results_summary(results_df, enrich):
    """검색 결과 요약 인포그래픽 카드 4개: 시장 분포 도넛 + 평균 등락률 + 평균 PER/ROE + 평균 목표가 상승여력."""
    n = len(results_df)
    n_kospi = int((results_df["시장"] == "KOSPI").sum())
    n_kosdaq = int((results_df["시장"] == "KOSDAQ").sum())
    avg_change = float(results_df["등락률(%)"].mean()) if n else 0.0

    # 카드 1: 발견 종목 (도넛 + 시장 분포)
    donut = donut_svg(
        [(n_kospi, "#dc2626", "코스피"), (n_kosdaq, "#2563eb", "코스닥")],
        size=68, thickness=8,
        center_text=str(n),
        center_sub="종목",
    )
    card_found = (
        f'<div class="ys-summary">'
        f'<div class="ys-summary-label">발견 종목 · 시장 분포</div>'
        f'<div class="ys-donut-row" style="margin-top:0.5rem">'
        f'<div>{donut}</div>'
        f'<div class="ys-donut-legend">'
        f'<div class="ys-donut-leg"><span><span class="dot" style="background:#dc2626"></span>코스피</span><span class="num">{n_kospi}</span></div>'
        f'<div class="ys-donut-leg"><span><span class="dot" style="background:#2563eb"></span>코스닥</span><span class="num">{n_kosdaq}</span></div>'
        f'</div>'
        f'</div>'
        f'</div>'
    )

    # 카드 2: 평균 등락률
    chg_klass = "index-up" if avg_change > 0 else ("index-down" if avg_change < 0 else "index-flat")
    chg_arrow = "▲" if avg_change > 0 else ("▼" if avg_change < 0 else "·")
    # 등락률을 -10% ~ +10% 범위 막대로
    chg_clamped = max(-10, min(10, avg_change))
    bar_pct = (chg_clamped + 10) / 20 * 100  # 0~100
    bar_color = "#dc2626" if avg_change > 0 else "#2563eb"
    card_change = (
        f'<div class="ys-summary">'
        f'<div class="ys-summary-label">평균 등락률 (당일)</div>'
        f'<div class="ys-summary-value {chg_klass}">{chg_arrow} {avg_change:+.2f}%</div>'
        f'<div class="ys-bar-track"><div class="ys-bar-fill" style="width:{bar_pct:.1f}%;background:{bar_color}"></div></div>'
        f'<div class="ys-summary-sub">전체 {n}개 종목 평균</div>'
        f'</div>'
    )

    # 카드 3 / 4 (enrich 시): 평균 ROE, 평균 목표가 상승여력
    if enrich and "ROE(%)" in results_df.columns:
        roe_series = pd.to_numeric(results_df["ROE(%)"], errors="coerce").dropna()
        per_series = pd.to_numeric(results_df["PER"], errors="coerce").dropna()
        upside_series = pd.to_numeric(results_df["목표가상승여력(%)"], errors="coerce").dropna()

        avg_roe = float(roe_series.mean()) if len(roe_series) else None
        avg_per = float(per_series.mean()) if len(per_series) else None
        avg_upside = float(upside_series.mean()) if len(upside_series) else None
        n_roe = len(roe_series)
        n_upside = len(upside_series)

        # 평균 ROE: 0~30% 막대
        if avg_roe is not None:
            roe_bar = max(0, min(30, avg_roe)) / 30 * 100
            card_roe = (
                f'<div class="ys-summary">'
                f'<div class="ys-summary-label">평균 ROE / PER</div>'
                f'<div class="ys-summary-value">{avg_roe:.1f}<span style="font-size:0.9rem;color:var(--text-muted);font-weight:500"> %</span></div>'
                f'<div class="ys-bar-track"><div class="ys-bar-fill" style="width:{roe_bar:.1f}%;background:#0f172a"></div></div>'
                f'<div class="ys-summary-sub">PER {avg_per:.2f} · 표본 {n_roe}개</div>'
                f'</div>'
            )
        else:
            card_roe = (
                f'<div class="ys-summary">'
                f'<div class="ys-summary-label">평균 ROE / PER</div>'
                f'<div class="ys-summary-value" style="color:var(--text-subtle)">—</div>'
                f'<div class="ys-summary-sub">데이터 없음</div>'
                f'</div>'
            )

        # 평균 목표가 상승여력: -30 ~ +50% 범위 막대
        if avg_upside is not None:
            up_klass = "index-up" if avg_upside > 0 else ("index-down" if avg_upside < 0 else "index-flat")
            up_arrow = "▲" if avg_upside > 0 else ("▼" if avg_upside < 0 else "·")
            up_clamped = max(-30, min(50, avg_upside))
            up_bar = (up_clamped + 30) / 80 * 100
            up_color = "#dc2626" if avg_upside > 0 else "#2563eb"
            card_upside = (
                f'<div class="ys-summary">'
                f'<div class="ys-summary-label">평균 목표가 상승여력</div>'
                f'<div class="ys-summary-value {up_klass}">{up_arrow} {avg_upside:+.1f}%</div>'
                f'<div class="ys-bar-track"><div class="ys-bar-fill" style="width:{up_bar:.1f}%;background:{up_color}"></div></div>'
                f'<div class="ys-summary-sub">컨센서스 보유 {n_upside}개 평균</div>'
                f'</div>'
            )
        else:
            card_upside = (
                f'<div class="ys-summary">'
                f'<div class="ys-summary-label">평균 목표가 상승여력</div>'
                f'<div class="ys-summary-value" style="color:var(--text-subtle)">—</div>'
                f'<div class="ys-summary-sub">컨센서스 데이터 없음</div>'
                f'</div>'
            )
    else:
        # 평균 거래량
        avg_vol = int(results_df["거래량"].mean()) if n else 0
        # 이평대비 평균
        avg_above = float(results_df["이평대비(%)"].mean()) if n else 0
        card_roe = (
            f'<div class="ys-summary">'
            f'<div class="ys-summary-label">평균 거래량</div>'
            f'<div class="ys-summary-value">{avg_vol:,}</div>'
            f'<div class="ys-summary-sub">발견 종목 평균</div>'
            f'</div>'
        )
        card_upside = (
            f'<div class="ys-summary">'
            f'<div class="ys-summary-label">평균 이평대비</div>'
            f'<div class="ys-summary-value">{avg_above:+.2f}%</div>'
            f'<div class="ys-summary-sub">현재가 vs 이동평균선</div>'
            f'</div>'
        )

    st.markdown(
        f'<div class="ys-summary-grid">{card_found}{card_change}{card_roe}{card_upside}</div>',
        unsafe_allow_html=True,
    )


def fetch_valuations_parallel(codes, progress_fn=None):
    """검색 결과 종목들에 대해 병렬로 valuation 조회. {code: dict} 반환."""
    out = {}
    total = len(codes)
    if total == 0:
        return out
    with concurrent.futures.ThreadPoolExecutor(max_workers=VALUATION_WORKERS) as pool:
        fut_map = {pool.submit(fetch_naver_valuation, c): c for c in codes}
        done = 0
        for fut in concurrent.futures.as_completed(fut_map):
            done += 1
            code = fut_map[fut]
            try:
                out[code] = fut.result() or {}
            except Exception:
                out[code] = {}
            if progress_fn:
                progress_fn(done, total)
    return out


# ============================================================
# 스크리닝 로직
# ============================================================
def _evaluate_ticker(row, start_str, end_str, ma_period, breakout_days, min_volume, min_price):
    """단일 종목 OHLCV → 이평선 돌파 조건 충족 시 결과 dict, 아니면 None."""
    df = _fetch_ohlcv_with_retry(row["code"], start_str, end_str)
    if df is None or len(df) < ma_period + 1:
        return None

    df = df.sort_index()
    df["MA"] = df["종가"].rolling(window=ma_period).mean()
    df = df.dropna(subset=["MA"])
    if len(df) < breakout_days + 1:
        return None

    recent = df.tail(breakout_days + 1).copy()
    recent["above"] = recent["종가"] > recent["MA"]

    crossed = False
    cross_date = None
    for i in range(1, len(recent)):
        if not recent.iloc[i - 1]["above"] and recent.iloc[i]["above"]:
            crossed = True
            cross_date = recent.index[i]
            break
    if not crossed:
        return None

    today_row = df.iloc[-1]
    if today_row["거래량"] < min_volume:
        return None
    if today_row["종가"] < min_price:
        return None
    if today_row["종가"] < today_row["MA"]:
        return None

    change_pct = ((today_row["종가"] - df.iloc[-2]["종가"]) / df.iloc[-2]["종가"]) * 100
    above_ma_pct = ((today_row["종가"] - today_row["MA"]) / today_row["MA"]) * 100

    return {
        "종목코드": row["code"],
        "종목명": row["name"],
        "시장": row["market"],
        "시총순위": int(row.get("rank", 0)) or None,
        "돌파일": cross_date.strftime("%Y-%m-%d"),
        "현재가": int(today_row["종가"]),
        "등락률(%)": round(change_pct, 2),
        f"{ma_period}일선": int(today_row["MA"]),
        "이평대비(%)": round(above_ma_pct, 2),
        "거래량": int(today_row["거래량"]),
    }


def screen_stocks(tickers_df, ma_period, breakout_days, min_volume, min_price, max_workers=MAX_WORKERS):
    """이평선 돌파 종목 스크리닝 (병렬)."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=int(ma_period * 1.6) + 30)
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")

    total = len(tickers_df)
    if total == 0:
        return pd.DataFrame()

    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    start_time = time.time()
    completed = 0
    rows = [r for _, r in tickers_df.iterrows()]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_row = {
            executor.submit(
                _evaluate_ticker, row, start_str, end_str,
                ma_period, breakout_days, min_volume, min_price,
            ): row
            for row in rows
        }
        for future in concurrent.futures.as_completed(future_to_row):
            completed += 1
            result = future.result()
            if result is not None:
                results.append(result)
            if completed % 5 == 0 or completed == total:
                progress_bar.progress(completed / total)
                elapsed = time.time() - start_time
                eta = (elapsed / completed) * (total - completed) if completed else 0
                status_text.text(
                    f"검색 중... {completed}/{total} | "
                    f"경과 {elapsed:.0f}초 / 남은 시간 약 {eta:.0f}초 | "
                    f"발견 {len(results)}개"
                )
    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(results)


def enrich_with_valuation(results_df):
    """검색 결과에 PER/PBR/ROE/PEG/목표가 컬럼 추가."""
    if len(results_df) == 0:
        return results_df

    codes = results_df["종목코드"].tolist()
    bar = st.progress(0)
    txt = st.empty()
    txt.text(f"가치 지표 수집 중... 0/{len(codes)}")

    def _progress(done, total):
        bar.progress(done / total)
        txt.text(f"가치 지표 수집 중... {done}/{total}")

    valuations = fetch_valuations_parallel(codes, progress_fn=_progress)
    bar.empty()
    txt.empty()

    results_df = results_df.copy()
    results_df["PER"] = [valuations.get(c, {}).get("per") for c in codes]
    results_df["PBR"] = [valuations.get(c, {}).get("pbr") for c in codes]
    results_df["ROE(%)"] = [valuations.get(c, {}).get("roe") for c in codes]
    results_df["PEG"] = [valuations.get(c, {}).get("peg") for c in codes]
    results_df["목표가"] = [valuations.get(c, {}).get("target_price") for c in codes]
    results_df["목표가일자"] = [valuations.get(c, {}).get("target_date") for c in codes]
    # 목표가 대비 현재가의 상승여력
    upside = []
    for c in codes:
        v = valuations.get(c, {})
        tp = v.get("target_price")
        cur = results_df.loc[results_df["종목코드"] == c, "현재가"].iloc[0]
        if tp and cur:
            upside.append(round((tp - cur) / cur * 100, 1))
        else:
            upside.append(None)
    results_df["목표가상승여력(%)"] = upside

    # 상세 표시용 dict도 함께 보관
    return results_df, valuations


# ============================================================
# 보조지표 계산
# ============================================================
def add_indicators(df, ma_periods=(5, 20, 60, 120), bb_period=20, bb_std=2):
    """plotly 차트에 쓸 이동평균선 + 볼린저밴드 + MACD + RSI 컬럼 추가."""
    df = df.copy()
    for p in ma_periods:
        df[f"MA{p}"] = df["종가"].rolling(window=p).mean()
    # Bollinger
    mid = df["종가"].rolling(window=bb_period).mean()
    std = df["종가"].rolling(window=bb_period).std()
    df["BB_MID"] = mid
    df["BB_UP"] = mid + bb_std * std
    df["BB_DN"] = mid - bb_std * std
    # MACD
    ema12 = df["종가"].ewm(span=12, adjust=False).mean()
    ema26 = df["종가"].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_SIG"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_HIST"] = df["MACD"] - df["MACD_SIG"]
    # RSI (14)
    delta = df["종가"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))
    return df


# ============================================================
# 상세 차트 (종목 detail panel)
# ============================================================
def build_chart(df, name, code, indicators):
    """캔들 + (선택된 보조지표) plotly 차트."""
    rows = ["price"]
    if indicators.get("volume"):
        rows.append("volume")
    if indicators.get("macd"):
        rows.append("macd")
    if indicators.get("rsi"):
        rows.append("rsi")
    n = len(rows)
    row_heights = [0.55] + [(0.45) / (n - 1) if n > 1 else 0.45] * (n - 1) if n > 1 else [1.0]

    fig = make_subplots(
        rows=n, cols=1, shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=row_heights,
    )

    UP, DOWN = "#dc2626", "#2563eb"

    # 1) 캔들 (KRX 컨벤션: 상승=빨강, 하락=파랑)
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["시가"], high=df["고가"], low=df["저가"], close=df["종가"],
        name="가격",
        increasing_line_color=UP, decreasing_line_color=DOWN,
        increasing_fillcolor=UP, decreasing_fillcolor=DOWN,
    ), row=1, col=1)

    # 이동평균선 — 절제된 톤
    ma_colors = {"MA5": "#94a3b8", "MA20": "#f59e0b", "MA60": "#10b981", "MA120": "#8b5cf6"}
    if indicators.get("ma"):
        for p in (5, 20, 60, 120):
            col = f"MA{p}"
            if col in df.columns:
                fig.add_trace(go.Scatter(
                    x=df.index, y=df[col], mode="lines", name=col,
                    line=dict(width=1.2, color=ma_colors[col]),
                    showlegend=True,
                ), row=1, col=1)

    # 볼린저밴드 — 은은한 회색 밴드
    if indicators.get("bb"):
        fig.add_trace(go.Scatter(
            x=df.index, y=df["BB_UP"], mode="lines", name="BB Upper",
            line=dict(width=0.6, color="rgba(100,116,139,0.45)"),
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["BB_DN"], mode="lines", name="BB Lower",
            line=dict(width=0.6, color="rgba(100,116,139,0.45)"),
            fill="tonexty", fillcolor="rgba(148,163,184,0.10)",
        ), row=1, col=1)

    cur_row = 2
    if indicators.get("volume"):
        colors = [UP if c >= o else DOWN for o, c in zip(df["시가"], df["종가"])]
        fig.add_trace(go.Bar(
            x=df.index, y=df["거래량"], name="거래량", marker_color=colors,
            marker_line_width=0,
            showlegend=False,
        ), row=cur_row, col=1)
        fig.update_yaxes(title_text="거래량", row=cur_row, col=1)
        cur_row += 1

    if indicators.get("macd"):
        fig.add_trace(go.Bar(
            x=df.index, y=df["MACD_HIST"], name="MACD Hist",
            marker_color=[UP if v >= 0 else DOWN for v in df["MACD_HIST"].fillna(0)],
            marker_line_width=0,
            showlegend=False,
        ), row=cur_row, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df["MACD"], name="MACD",
                                  line=dict(color="#0f172a", width=1.2)),
                      row=cur_row, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df["MACD_SIG"], name="Signal",
                                  line=dict(color="#f59e0b", width=1.2)),
                      row=cur_row, col=1)
        fig.update_yaxes(title_text="MACD", row=cur_row, col=1)
        cur_row += 1

    if indicators.get("rsi"):
        fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], name="RSI(14)",
                                  line=dict(color="#0f172a", width=1.2)),
                      row=cur_row, col=1)
        fig.add_hline(y=70, line=dict(color="rgba(220,38,38,0.35)", dash="dash"), row=cur_row, col=1)
        fig.add_hline(y=30, line=dict(color="rgba(37,99,235,0.35)", dash="dash"), row=cur_row, col=1)
        fig.update_yaxes(title_text="RSI", range=[0, 100], row=cur_row, col=1)

    # 차트 전반 톤 — 흰 배경 + 옅은 그리드 + 모노 폰트 hover
    fig.update_layout(
        title=dict(
            text=f"<b>{name}</b> <span style='color:#94a3b8;font-weight:400'>{code}</span>",
            font=dict(family="Pretendard, Inter, system-ui, sans-serif", size=16, color="#0f172a"),
            x=0.0, xanchor="left", y=0.98, yanchor="top",
        ),
        xaxis_rangeslider_visible=False,
        height=200 + 220 * n,
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, x=0,
            font=dict(family="Pretendard, Inter, system-ui, sans-serif", size=11, color="#475569"),
            bgcolor="rgba(0,0,0,0)",
        ),
        hovermode="x unified",
        # 마우스 드래그 시 패닝(이동)을 기본 동작으로
        dragmode="pan",
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(family="Pretendard, Inter, system-ui, sans-serif", color="#0f172a", size=11),
        hoverlabel=dict(
            bgcolor="#0f172a",
            font=dict(family="JetBrains Mono, monospace", size=11, color="#ffffff"),
            bordercolor="#0f172a",
        ),
    )
    fig.update_xaxes(
        rangebreaks=[dict(bounds=["sat", "mon"])],
        showgrid=True, gridcolor="#f1f5f9", gridwidth=1,
        showline=True, linecolor="#e5e7eb",
        ticks="outside", tickcolor="#cbd5e1",
    )
    fig.update_yaxes(
        showgrid=True, gridcolor="#f1f5f9", gridwidth=1,
        showline=True, linecolor="#e5e7eb",
        zeroline=False,
        ticks="outside", tickcolor="#cbd5e1",
    )
    return fig


def render_detail_panel(code, name, valuation, ma_period_main):
    """선택한 종목의 차트 + 가치 카드 + 컨센서스 + 리포트 리스트."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=400)  # 약 1년 + 보조지표 워밍업
    df = _fetch_ohlcv_with_retry(code, start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d"), retries=1)
    if df is None or len(df) == 0:
        st.warning("일봉 데이터를 불러오지 못했습니다.")
        return

    df = df.sort_index()
    df = add_indicators(df)

    # 보조지표 토글
    cc = st.columns([1, 1, 1, 1, 1])
    with cc[0]:
        opt_ma = st.checkbox("이동평균(5/20/60/120)", value=True, key=f"opt_ma_{code}")
    with cc[1]:
        opt_bb = st.checkbox("볼린저밴드(20,2)", value=True, key=f"opt_bb_{code}")
    with cc[2]:
        opt_vol = st.checkbox("거래량", value=True, key=f"opt_vol_{code}")
    with cc[3]:
        opt_macd = st.checkbox("MACD(12,26,9)", value=False, key=f"opt_macd_{code}")
    with cc[4]:
        opt_rsi = st.checkbox("RSI(14)", value=False, key=f"opt_rsi_{code}")

    indicators = {"ma": opt_ma, "bb": opt_bb, "volume": opt_vol, "macd": opt_macd, "rsi": opt_rsi}

    chart_col, info_col = st.columns([3, 2])

    with chart_col:
        fig = build_chart(df, name, code, indicators)
        st.plotly_chart(
            fig,
            use_container_width=True,
            config={
                # 휠 줌 + 패닝 활성화
                "scrollZoom": True,
                "displaylogo": False,
                "displayModeBar": True,
                "modeBarButtonsToAdd": ["pan2d", "zoomIn2d", "zoomOut2d", "autoScale2d", "resetScale2d"],
                "modeBarButtonsToRemove": ["select2d", "lasso2d"],
                "doubleClick": "reset+autosize",
                "toImageButtonOptions": {"format": "png", "filename": f"{name}_{code}"},
            },
        )
        st.caption("💡 마우스 휠 = 확대/축소, 드래그 = 이동, 더블클릭 = 초기화")

    with info_col:
        v = valuation or {}
        per = v.get("per")
        pbr = v.get("pbr")
        roe = v.get("roe")
        peg = v.get("peg")
        cns_per = v.get("cns_per")
        eps = v.get("eps")
        bps = v.get("bps")
        div = v.get("dividend_yield")
        roe_year = v.get("roe_year")
        per_desc = v.get("per_desc")

        def _fmt(val, fmt="{:.2f}", dash="—"):
            return fmt.format(val) if val is not None else dash

        def _stat(label, value, sub=""):
            sub_html = f'<div class="ys-stat-sub">{sub}</div>' if sub else ""
            return (
                f'<div class="ys-stat">'
                f'<div class="ys-stat-label">{label}</div>'
                f'<div class="ys-stat-value">{value}</div>'
                f'{sub_html}'
                f'</div>'
            )

        st.markdown('<div class="ys-section-label">VALUATION</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="ys-stat-grid">'
            + _stat("PER", _fmt(per), per_desc or "")
            + _stat("PBR", _fmt(pbr), v.get("pbr_desc") or "")
            + _stat("ROE", f"{_fmt(roe)}%" if roe is not None else "—",
                    f"{roe_year[:4]}.{roe_year[4:6]}" if roe_year else "")
            + _stat("PEG", _fmt(peg), "PER ÷ EPS 성장률")
            + _stat("EPS", _fmt(eps, "{:,}") + ("원" if eps is not None else ""))
            + _stat("BPS", _fmt(bps, "{:,}") + ("원" if bps is not None else ""))
            + _stat("배당수익률", f"{_fmt(div)}%" if div is not None else "—")
            + _stat("추정 PER", _fmt(cns_per), "12개월 추정 EPS 기준")
            + '</div>',
            unsafe_allow_html=True,
        )
        st.caption("FCF는 DART 공시 연동이 필요해 현재 표시되지 않습니다.")

        # 컨센서스 박스
        st.markdown('<div class="ys-section-label">CONSENSUS</div>', unsafe_allow_html=True)
        tp = v.get("target_price")
        td = v.get("target_date")
        rc = v.get("target_recomm")
        if tp:
            cur = float(df["종가"].iloc[-1])
            upside = (tp - cur) / cur * 100
            up_klass = "index-up" if upside > 0 else ("index-down" if upside < 0 else "index-flat")
            if rc and rc >= 4.5:
                opinion, pill = "강력매수", "is-buy"
            elif rc and rc >= 3.5:
                opinion, pill = "매수", "is-buy"
            elif rc and rc >= 2.5:
                opinion, pill = "중립", "is-hold"
            elif rc:
                opinion, pill = "매도", "is-sell"
            else:
                opinion, pill = "—", "is-hold"
            opinion_pill = f'<span class="ys-pill {pill}">{opinion}{f" {rc:.2f}/5" if rc else ""}</span>'
            st.markdown(
                f'<div class="ys-consensus">'
                f'<div style="color:var(--text-muted);font-size:0.78rem;font-weight:500;letter-spacing:0.04em;text-transform:uppercase">평균 목표주가</div>'
                f'<div style="margin-top:0.3rem">'
                f'<span class="target-price">{tp:,}<span style="font-size:0.95rem;color:var(--text-muted);font-weight:500"> 원</span></span>'
                f'<span class="upside {up_klass}">{upside:+.1f}%</span>'
                f'</div>'
                f'<div class="meta">기준일 {td or "—"} · 투자의견 {opinion_pill}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.caption("컨센서스 정보가 없습니다.")

        # 리포트 리스트
        st.markdown('<div class="ys-section-label" style="margin-top:1.2rem">RECENT RESEARCH</div>',
                    unsafe_allow_html=True)
        researches = v.get("researches") or []
        if not researches:
            st.caption("리포트 정보가 없습니다.")
        else:
            html_parts = []
            for r in researches:
                date = r.get("date") or ""
                if len(date) == 8:
                    date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
                html_parts.append(
                    f'<div class="ys-report">'
                    f'<div class="meta"><span class="date">{date}</span><span class="broker">{r.get("broker", "—")}</span></div>'
                    f'<div class="title">{r.get("title", "")}</div>'
                    f'</div>'
                )
            st.markdown("".join(html_parts), unsafe_allow_html=True)

    # 면책 문구
    st.caption("⚠ 본 화면의 가치 지표/목표가는 네이버 증권 공개 데이터를 기반으로 하며, "
               "매수 추천이 아닙니다. 투자 판단은 본인 책임입니다.")


# ============================================================
# UI: 헤더 & 사이드바 & 메인
# ============================================================
st.markdown(
    '<div class="ys-eyebrow">YS QUANT · KR EQUITY SCREENER</div>'
    '<h1 class="ys-title"><em>YS Quant Trading</em></h1>'
    '<p class="ys-subtitle">코스피·코스닥 종목 중 일봉 종가가 N일 이동평균선을 돌파한 종목을 찾고, '
    '가치 지표와 증권사 컨센서스 목표가까지 한 화면에서 확인합니다.</p>',
    unsafe_allow_html=True,
)

render_market_indices()
st.markdown('<hr class="ys-divider"/>', unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ 검색 조건")
    ma_period = st.selectbox("이동평균선 기간", options=[20, 60, 100, 200, 300], index=4,
                             help="일봉 종가 기준 N일 이동평균선")
    market = st.multiselect("시장", options=["KOSPI", "KOSDAQ"], default=["KOSPI", "KOSDAQ"])
    st.markdown("**📊 시가총액 상위 N개**")
    st.caption("스캔 범위를 시총 상위로 좁히면 훨씬 빠릅니다.")
    TOP_N_OPTIONS = ["100", "200", "300", "500", "1000", "전체"]
    kospi_top = st.selectbox("KOSPI", options=TOP_N_OPTIONS, index=1)
    kosdaq_top = st.selectbox("KOSDAQ", options=TOP_N_OPTIONS, index=1)

    breakout_days = st.slider("돌파 시점 (최근 N일 이내)", min_value=1, max_value=10, value=3)
    min_volume = st.number_input("최소 거래량 (당일)", min_value=0, value=10000, step=10000)
    min_price = st.number_input("최소 주가 (원)", min_value=0, value=1000, step=500)

    st.divider()
    enrich = st.checkbox("가치 지표/목표가 함께 가져오기", value=True,
                        help="검색 후 결과 종목의 네이버 모바일 stock JSON을 호출해 PER/PBR/ROE/목표가를 추가로 채웁니다.")
    st.caption("💡 데이터: FinanceDataReader (종목/시총/지수) + pykrx (일봉) + 네이버 모바일 stock JSON (가치)")
    st.caption(f"⚡ 병렬 호출 {MAX_WORKERS}개, 타임아웃 {REQUEST_TIMEOUT_SEC}초, 재시도 {RETRY_COUNT}회")
    st.caption("⏱️ 예상: 상위 200+200 약 30초~1분, 전체 약 3~5분")

    run_button = st.button("🔍 스크리닝 시작", type="primary", use_container_width=True)


if run_button:
    if not market:
        st.error("시장을 1개 이상 선택해주세요.")
        st.stop()

    top_n_per_market = {}
    if "KOSPI" in market:
        top_n_per_market["KOSPI"] = None if kospi_top == "전체" else int(kospi_top)
    if "KOSDAQ" in market:
        top_n_per_market["KOSDAQ"] = None if kosdaq_top == "전체" else int(kosdaq_top)

    with st.spinner("종목 리스트 로딩 중..."):
        tickers_df = get_ticker_list(market, top_n_per_market)
    if len(tickers_df) == 0:
        st.error("종목 리스트를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.")
        st.stop()

    scope_desc = " · ".join(
        f"{m} {'전체' if top_n_per_market.get(m) is None else f'상위 {top_n_per_market[m]}'}"
        for m in market
    )
    st.info(f"📋 {scope_desc} → 총 {len(tickers_df)}개 종목 스캔 시작 ({ma_period}일선 돌파 검색)")

    t0 = time.time()
    results_df = screen_stocks(tickers_df, ma_period, breakout_days, min_volume, min_price)
    elapsed = time.time() - t0

    if len(results_df) == 0:
        st.warning(f"⚠️ 조건에 맞는 종목이 없습니다 (소요 {elapsed:.1f}초). 조건을 완화해보세요.")
        st.stop()

    valuations = {}
    if enrich:
        results_df, valuations = enrich_with_valuation(results_df)

    # 등락률 기준 정렬
    results_df = results_df.sort_values("등락률(%)", ascending=False).reset_index(drop=True)

    st.success(f"✅ 완료! 소요시간 {elapsed:.1f}초 · 검색 결과 **{len(results_df)}개 종목**")

    render_results_summary(results_df, enrich)

    st.markdown('<hr class="ys-divider"/>', unsafe_allow_html=True)

    # 결과 테이블 (종목명/종목코드 → 네이버 LinkColumn)
    display_df = results_df.copy()
    display_df["종목명"] = display_df.apply(
        lambda r: f"https://finance.naver.com/item/main.naver?code={r['종목코드']}#{r['종목명']}",
        axis=1,
    )
    display_df["종목코드"] = display_df["종목코드"].apply(
        lambda c: f"https://finance.naver.com/item/main.naver?code={c}"
    )

    column_config = {
        "종목명": st.column_config.LinkColumn(
            "종목명", help="클릭하면 네이버 증권에서 열립니다", display_text=r"#(.+)$"
        ),
        "종목코드": st.column_config.LinkColumn(
            "종목코드", help="클릭하면 네이버 증권에서 열립니다", display_text=r"code=(\d+)"
        ),
        "시총순위": st.column_config.NumberColumn(format="%d위"),
        "현재가": st.column_config.NumberColumn(format="%d 원"),
        f"{ma_period}일선": st.column_config.NumberColumn(format="%d 원"),
        "거래량": st.column_config.NumberColumn(format="%d"),
        "등락률(%)": st.column_config.NumberColumn(format="%.2f%%"),
        "이평대비(%)": st.column_config.NumberColumn(format="%.2f%%"),
    }
    if enrich:
        column_config.update({
            "PER": st.column_config.NumberColumn(format="%.2f"),
            "PBR": st.column_config.NumberColumn(format="%.2f"),
            "ROE(%)": st.column_config.NumberColumn(format="%.2f"),
            "PEG": st.column_config.NumberColumn(format="%.2f"),
            "목표가": st.column_config.NumberColumn(format="%d 원"),
            "목표가상승여력(%)": st.column_config.NumberColumn(format="%.1f%%"),
        })

    st.dataframe(display_df, use_container_width=True, hide_index=True, column_config=column_config)

    # CSV 다운로드
    csv = results_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 CSV 다운로드", csv,
        f"breakout_{ma_period}MA_{datetime.now().strftime('%Y%m%d')}.csv",
        "text/csv",
    )

    # 상세 차트 패널
    st.divider()
    st.subheader("🔍 종목 상세 보기")
    label_to_code = {
        f"{r['종목명']} ({r['종목코드']}, {r['시장']})": r["종목코드"]
        for _, r in results_df.iterrows()
    }
    sel_label = st.selectbox("상세 차트 종목 선택", options=list(label_to_code.keys()))
    if sel_label:
        sel_code = label_to_code[sel_label]
        sel_name = results_df.loc[results_df["종목코드"] == sel_code, "종목명"].iloc[0]
        if sel_code not in valuations and enrich:
            valuations[sel_code] = fetch_naver_valuation(sel_code)
        render_detail_panel(sel_code, sel_name, valuations.get(sel_code, {}), ma_period)

    # 결과를 세션에 저장 (재실행 시 사용)
    st.session_state["last_results"] = results_df
    st.session_state["last_valuations"] = valuations

else:
    # 비실행 상태에서도 직전 결과가 있으면 상세 차트 패널 사용 가능
    if st.session_state.get("last_results") is not None and len(st.session_state.get("last_results", [])) > 0:
        st.info("👈 사이드바에서 조건을 바꿔 다시 검색하거나, 아래에서 직전 결과의 종목 상세를 볼 수 있습니다.")
        results_df = st.session_state["last_results"]
        valuations = st.session_state.get("last_valuations") or {}

        display_df = results_df.copy()
        display_df["종목명"] = display_df.apply(
            lambda r: f"https://finance.naver.com/item/main.naver?code={r['종목코드']}#{r['종목명']}",
            axis=1,
        )
        display_df["종목코드"] = display_df["종목코드"].apply(
            lambda c: f"https://finance.naver.com/item/main.naver?code={c}"
        )
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "종목명": st.column_config.LinkColumn("종목명", display_text=r"#(.+)$"),
                "종목코드": st.column_config.LinkColumn("종목코드", display_text=r"code=(\d+)"),
            },
        )
        st.subheader("🔍 종목 상세 보기")
        label_to_code = {
            f"{r['종목명']} ({r['종목코드']}, {r['시장']})": r["종목코드"]
            for _, r in results_df.iterrows()
        }
        sel_label = st.selectbox("상세 차트 종목 선택", options=list(label_to_code.keys()))
        if sel_label:
            sel_code = label_to_code[sel_label]
            sel_name = results_df.loc[results_df["종목코드"] == sel_code, "종목명"].iloc[0]
            render_detail_panel(sel_code, sel_name, valuations.get(sel_code, {}), 60)
    else:
        st.info("👈 사이드바에서 조건을 설정하고 **스크리닝 시작** 버튼을 누르세요.")
        with st.expander("📖 사용 가이드"):
            st.markdown("""
            ### 이 도구는 무엇인가요?
            장기 이동평균선을 돌파한 종목을 자동으로 찾아주고, 검색 결과 각 종목의
            **가치 지표(PER/PBR/ROE/PEG)** 와 **증권사 평균 목표가**, 캔들 차트(이평/볼린저/거래량/MACD/RSI)까지
            한 화면에서 확인할 수 있게 해 줍니다.

            ### 검색 조건
            - **이동평균선 기간**: 20/60/100/200/300일선 중 선택 (기본 300일)
            - **시장 + 시가총액 상위 N**: 스캔 범위를 줄이면 훨씬 빠릅니다.
            - **돌파 시점**: 최근 며칠 이내에 돌파한 종목만 (1~10일)
            - **최소 거래량/주가**: 동전주, 거래량 미달 종목 필터링

            ### 결과 해석
            - **돌파일**: 종가가 이평선을 처음 위로 뚫은 날
            - **이평대비(%)**: 현재가가 이평선 대비 몇 % 위에 있는지
            - **목표가상승여력(%)**: 평균 목표주가 대비 현재가의 상승 여력

            ### 데이터 출처
            - 종목/시가총액/지수: FinanceDataReader (KRX 공개)
            - 일봉 OHLCV: pykrx (KRX 공식)
            - 가치 지표/목표가: 네이버 모바일 stock JSON

            ### 주의사항
            - 본 도구는 정보 제공 목적이며 매수 추천이 아닙니다.
            - 데이터의 정확성을 보장하지 않습니다.
            """)

# 메인 페이지 하단 면책 / 푸터
st.markdown(
    '<div class="ys-footer">'
    '<strong>YS QUANT TRADING</strong> · 정보 제공 목적의 도구이며 매수 추천이 아닙니다. '
    '데이터의 정확성을 보장하지 않으며, 투자 판단의 결과는 사용자 본인에게 있습니다.'
    '</div>',
    unsafe_allow_html=True,
)
