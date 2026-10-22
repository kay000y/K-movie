from datetime import datetime, timedelta
import urllib.parse
import zoneinfo
import pandas as pd
import requests
import streamlit as st

# 페이지 기본 설정
st.set_page_config(
    page_title="박스오피스 탐색기", layout="wide", initial_sidebar_state="expanded"
)

# 0. 다크모드 전환 스위치 (오른쪽 위 상단)
# Streamlit의 Session State를 활용하여 라이트/다크모드 CSS를 동적으로 전환합니다.
if "theme_mode" not in st.session_state:
    st.session_state["theme_mode"] = "dark"  # 기본값: 다크모드

top_col1, top_col2 = st.columns([8, 2])
with top_col1:
    st.title("🎬 KOBIS 일별 박스오피스 탐색기")
with top_col2:
    mode_toggle = st.toggle("🌙 다크모드", value=st.session_state["theme_mode"] == "dark")
    st.session_state["theme_mode"] = "dark" if mode_toggle else "light"

# 선택된 모드에 맞춰 커스텀 스타일(CSS) 적용
if st.session_state["theme_mode"] == "dark":
    st.markdown(
        """
        <style>
            .stApp {
                background-color: #0E1117;
                color: #FFFFFF;
            }
            .stMetric {
                background-color: #1E222B;
                padding: 15px;
                border-radius: 10px;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        """
        <style>
            .stApp {
                background-color: #FFFFFF;
                color: #000000;
            }
            .stMetric {
                background-color: #F0F2F6;
                padding: 15px;
                border-radius: 10px;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


# 1. 한국 표준시(KST) 기준 날짜 계산
def get_kst_today_and_yesterday():
    kst = zoneinfo.ZoneInfo("Asia/Seoul")
    now_kst = datetime.now(kst)
    today = now_kst.date()
    yesterday = today - timedelta(days=1)
    return today, yesterday


today_kst, max_date = get_kst_today_and_yesterday()

# 2. 사이드바 날짜 선택
st.sidebar.header("🗓️ 날짜 선택")
selected_date = st.sidebar.date_input(
    label="조회할 날짜를 선택하세요 (어제까지 선택 가능)",
    value=max_date,
    max_value=max_date,
)

target_dt_param = selected_date.strftime("%Y%m%d")
target_dt_display = selected_date.strftime("%Y년 %m월 %d일")

st.subheader(f"📅 조회 기준일자: {target_dt_display}")


# 3. KOBIS 일별 박스오피스 API 불러오기
@st.cache_data(ttl=3600)
def fetch_box_office(api_key, target_dt):
    url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
    params = {"key": api_key, "targetDt": target_dt}

    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            return None, f"서버 응답 오류 (상태 코드: {response.status_code})"

        data = response.json()

        if "faultInfo" in data:
            message = data["faultInfo"].get(
                "message", "인증키 또는 API 요청 오류입니다."
            )
            return None, f"KOBIS API 오류: {message}"

        box_office_result = data.get("boxOfficeResult", {})
        daily_list = box_office_result.get("dailyBoxOfficeList", [])

        if not daily_list:
            return None, "그날은 아직 집계 전입니다"

        return daily_list, None

    except requests.exceptions.RequestException as e:
        return None, f"네트워크 통신 중 오류가 발생했습니다: {e}"


# 4. 영화 포스터 URL 불러오기 (개선된 하이브리드 검색 방식)
@st.cache_data(ttl=86400)
def fetch_poster_url(movie_name):
    # 특수문자 제거 후 순수 영화 제목 추출
    clean_name = movie_name.split("(")[0].strip()

    # 1차: TMDB API 검색
    tmdb_url = "https://api.themoviedb.org/3/search/movie"
    params = {
        "api_key": "15d2ea6d0dc1d476efbca3ecc92b2624",
        "query": clean_name,
        "language": "ko-KR",
    }
    try:
        res = requests.get(tmdb_url, params=params, timeout=3)
        if res.status_code == 200:
            results = res.json().get("results", [])
            for item in results:
                if item.get("poster_path"):
                    return f"https://image.tmdb.org/t/p/w500{item['poster_path']}"
    except Exception:
        pass

    # 2차: 대체 이미지 (커스텀 영화 플레이스홀더 포스터)
    encoded_title = urllib.parse.quote(clean_name)
    return f"https://placehold.co/300x450/222222/FFFFFF/png?text={encoded_title}"


# 5. API 키 검증
if "KOBIS_KEY" not in st.secrets:
    st.error("🔑 API 인증키가 설정되지 않았습니다.")
    st.info(
        "**확인 안내:** Streamlit Cloud의 Secrets에 `KOBIS_KEY`를 설정해 주세요."
    )
    st.stop()

api_key = st.secrets["KOBIS_KEY"]

# 6. 데이터 요청 실행
movies, error_msg = fetch_box_office(api_key, target_dt_param)

if error_msg:
    if error_msg == "그날은 아직 집계 전입니다":
        st.warning(f"💡 {target_dt_display}은(는) 아직 집계 전입니다.")
        st.info("다른 이전 날짜를 선택하여 조회해 주세요.")
    else:
        st.error("⚠️ 데이터를 불러오지 못했습니다.")
        st.warning(f"**상세 원인:** {error_msg}")
    st.stop()

# 7. 데이터 가공
df = pd.DataFrame(movies)

num_cols = ["rank", "rankInten", "audiCnt", "audiAcc", "scrnCnt"]
for col in num_cols:
    df[col] = pd.to_numeric(df[col], errors="coerce")


# 누적관객 100만 이상 시 트로피 이모지(🏆) 추가
def format_movie_name(row):
    name = row["movieNm"]
    if row["audiAcc"] >= 1_000_000:
        return f"{name} 🏆"
    return name


df["movieNm_display"] = df.apply(format_movie_name, axis=1)


# 순위 증감 화살표 가공
def format_rank_inten(val):
    if val > 0:
        return f"🔺 {val}"
    elif val < 0:
        return f"🔹 {abs(val)}"
    else:
        return "-"


df["rankInten_display"] = df["rankInten"].apply(format_rank_inten)

# 8. 1위 영화 지표 카드
top_movie = df.iloc[0]

st.markdown("---")
st.markdown(f"### 🥇 1위 영화: **{top_movie['movieNm_display']}**")

col1, col2, col3 = st.columns(3)
with col1:
    st.metric(label="일일 관객수", value=f"{top_movie['audiCnt']:,} 명")
with col2:
    st.metric(label="누적 관객수", value=f"{top_movie['audiAcc']:,} 명")
with col3:
    st.metric(label="스크린 수", value=f"{top_movie['scrnCnt']:,} 개")

st.markdown("---")

# 9. 관객수 상위 5편 막대그래프
st.subheader("📊 관객수 상위 5개 영화")
top_5_df = df.head(5).copy()
chart_df = top_5_df[["movieNm", "audiCnt"]].set_index("movieNm")
chart_df.columns = ["일일 관객수"]
st.bar_chart(chart_df)

st.markdown("---")

# 10. 박스오피스 전체 순위 표
st.subheader("📋 박스오피스 전체 순위 (Top 10)")

display_df = df[
    [
        "rank",
        "rankInten_display",
        "movieNm_display",
        "openDt",
        "audiCnt",
        "audiAcc",
        "scrnCnt",
    ]
].copy()

display_df.columns = [
    "순위",
    "순위변동",
    "영화명",
    "개봉일",
    "관객수",
    "누적관객",
    "스크린수",
]

st.dataframe(
    display_df.style.format(
        {"관객수": "{:,} 명", "누적관객": "{:,} 명", "스크린수": "{:,} 개"}
    ),
    use_container_width=True,
    hide_index=True,
)

st.markdown("---")

# 11. 맨 아래: 순위별 영화 포스터 (1위~5위 / 6위~10위)
st.subheader("🖼️ 박스오피스 Top 10 영화 포스터")

# 1위 ~ 5위 포스터 (첫 번째 줄)
st.markdown("#### 🔝 1위 ~ 5위")
cols_top5 = st.columns(5)
for idx, row in enumerate(df.head(5).itertuples()):
    with cols_top5[idx]:
        poster_url = fetch_poster_url(row.movieNm)
        st.image(
            poster_url,
            use_column_width=True,
            caption=f"{row.rank}위: {row.movieNm}",
        )

st.write("")  # 한 칸 띄우기

# 6위 ~ 10위 포스터 (두 번째 줄)
if len(df) >= 10:
    st.markdown("#### 🎬 6위 ~ 10위")
    cols_next5 = st.columns(5)
    for idx, row in enumerate(df.iloc[5:10].itertuples()):
        with cols_next5[idx]:
            poster_url = fetch_poster_url(row.movieNm)
            st.image(
                poster_url,
                use_column_width=True,
                caption=f"{row.rank}위: {row.movieNm}",
            )
