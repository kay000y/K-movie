from datetime import datetime, timedelta
import zoneinfo
import urllib.parse
import pandas as pd
import requests
import streamlit as st

# 페이지 기본 설정 (제목 및 넓은 레이아웃)
st.set_page_config(page_title="박스오피스 탐색기", layout="wide")

st.title("🎬 KOBIS 일별 박스오피스 탐색기")


# 1. 한국 표준시(KST) 기준 날짜 계산 함수
def get_kst_today_and_yesterday():
    kst = zoneinfo.ZoneInfo("Asia/Seoul")
    now_kst = datetime.now(kst)
    today = now_kst.date()
    yesterday = today - timedelta(days=1)
    return today, yesterday


today_kst, max_date = get_kst_today_and_yesterday()

# 2. 사이드바 날짜 선택 (최대 고를 수 있는 날짜는 어제까지로 제한)
st.sidebar.header("🗓️ 날짜 선택")
selected_date = st.sidebar.date_input(
    label="조회할 날짜를 선택하세요 (어제까지 선택 가능)",
    value=max_date,
    max_value=max_date,
)

target_dt_param = selected_date.strftime("%Y%m%d")
target_dt_display = selected_date.strftime("%Y년 %m월 %d일")

st.subheader(f"📅 조회 기준일자: {target_dt_display}")


# 3. API 데이터 가져오기 함수 (캐싱 적용)
@st.cache_data(ttl=3600)
def fetch_box_office(api_key, target_dt):
    url = (
        "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
    )
    params = {"key": api_key, "targetDt": target_dt}

    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            return None, f"서버 응답 오류 (상태 코드: {response.status_code})"

        data = response.json()

        # KOBIS 특이사항: 인증키 오류 시 200 OK와 함께 faultInfo 반환
        if "faultInfo" in data:
            message = data["faultInfo"].get(
                "message", "인증키 또는 API 요청 오류입니다."
            )
            return None, f"KOBIS API 오류: {message}"

        box_office_result = data.get("boxOfficeResult", {})
        daily_list = box_office_result.get("dailyBoxOfficeList", [])

        # 영화 목록이 빈 경우 (요청사항 반영: "그날은 아직 집계 전입니다")
        if not daily_list:
            return None, "그날은 아직 집계 전입니다"

        return daily_list, None

    except requests.exceptions.RequestException as e:
        return None, f"네트워크 통신 중 오류가 발생했습니다: {e}"


# 4. 비밀 금고(st.secrets)에서 API 키 검증
if "KOBIS_KEY" not in st.secrets:
    st.error("🔑 API 인증키가 설정되지 않았습니다.")
    st.info(
        "**확인 안내:**\n"
        "Streamlit Cloud의 App Settings -> **Secrets**에 `KOBIS_KEY`를 설정해 주세요."
    )
    st.stop()

api_key = st.secrets["KOBIS_KEY"]

# 5. 데이터 요청 실행 및 오류/집계 전 안내
movies, error_msg = fetch_box_office(api_key, target_dt_param)

if error_msg:
    if error_msg == "그날은 아직 집계 전입니다":
        st.warning(f"💡 {target_dt_display}은(는) 아직 집계 전입니다.")
        st.info("다른 이전 날짜를 선택하여 조회해 주세요.")
    else:
        st.error("⚠️ 데이터를 불러오지 못했습니다.")
        st.warning(f"**상세 원인:** {error_msg}")
        st.markdown(
            """
            ---
            ### 💡 확인 안내
            - **KOBIS API 인증키:** Secrets의 `KOBIS_KEY` 값이 정확한지 확인하세요.
            - **일일 트래픽:** KOBIS API 사용량 초과 여부를 확인하세요.
            """
        )
    st.stop()

# 6. 데이터 가공
df = pd.DataFrame(movies)

# 숫자 데이터 형변환
num_cols = ["rank", "rankInten", "audiCnt", "audiAcc", "scrnCnt"]
for col in num_cols:
    df[col] = pd.to_numeric(df[col], errors="coerce")


# 영화명 가공: 누적관객 100만 이상 시 트로피 이모지(🏆) 추가
def format_movie_name(row):
    name = row["movieNm"]
    if row["audiAcc"] >= 1_000_000:
        return f"{name} 🏆"
    return name


df["movieNm_display"] = df.apply(format_movie_name, axis=1)


# 순위 증감 가공: 양수는 빨간 위 화살표(🔺), 음수는 파란 아래 화살표(🔹), 0은 동일(-)
def format_rank_inten(val):
    if val > 0:
        return f"🔺 {val}"
    elif val < 0:
        return f"🔹 {abs(val)}"
    else:
        return "-"


df["rankInten_display"] = df["rankInten"].apply(format_rank_inten)

# 7. 1위 영화 지표 카드 (Metrics)
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

# 8. 영화 포스터 바로가기 영역 (구글 이미지 검색 연동)
# 웹 크롤링/무단 링크 차단 이슈를 방지하고 안전하게 구글 포스터 검색 결과를 카드 형태로 연결합니다.
st.subheader("🖼️ 순위별 영화 포스터 검색")
st.caption("각 영화 카드를 클릭하면 구글의 공식 메인 포스터 검색 결과로 바로 이동합니다.")

cols = st.columns(5)
for idx, row in enumerate(df.head(5).itertuples()):
    with cols[idx]:
        search_query = urllib.parse.quote(f"영화 {row.movieNm} 포스터")
        google_images_url = f"https://www.google.com/search?tbm=isch&q={search_query}"

        st.markdown(f"**{row.rank}위. {row.movieNm_display}**")
        st.markdown(
            f"[🖼️ 구글 메인 포스터 보기]({google_images_url})",
            unsafe_allow_html=True,
        )

st.markdown("---")

# 9. 관객수 상위 5편 막대그래프
st.subheader("📊 관객수 상위 5개 영화")
top_5_df = df.head(5).copy()
chart_df = top_5_df[["movieNm", "audiCnt"]].set_index("movieNm")
chart_df.columns = ["일일 관객수"]
st.bar_chart(chart_df)

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
