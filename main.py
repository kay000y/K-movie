from datetime import datetime, timedelta
import zoneinfo
import pandas as pd
import requests
import streamlit as st

# 페이지 기본 설정 (제목 및 넓은 레이아웃)
st.set_page_config(page_title="어제 박스오피스", layout="wide")

st.title("🎬 어제 박스오피스 Top 10")


# 1. 날짜 계산 (한국 표준시 KST 기준 어제 날짜)
# 배포 서버의 시계가 해외 기준이어도 한국 시간(Asia/Seoul)으로 정확히 계산합니다.
def get_yesterday_kst():
    kst = zoneinfo.ZoneInfo("Asia/Seoul")
    now_kst = datetime.now(kst)
    yesterday_kst = now_kst - timedelta(days=1)
    return yesterday_kst.strftime("%Y%m%d"), yesterday_kst.strftime(
        "%Y년 %m월 %d일"
    )


target_dt_param, target_dt_display = get_yesterday_kst()
st.subheader(f"📅 기준일자: {target_dt_display}")


# 2. API 데이터 가져오기 함수 (캐싱 적용으로 호출 절약)
@st.cache_data(ttl=3600)  # 1시간 동안 결과를 기억하여 중복 요청을 방지합니다.
def fetch_box_office(api_key, target_dt):
    url = (
        "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
    )
    params = {"key": api_key, "targetDt": target_dt}

    try:
        response = requests.get(url, params=params, timeout=10)
        # 네트워크 응답 자체가 실패한 경우 (404, 500 등)
        if response.status_code != 200:
            return None, f"서버 응답 오류 (상태 코드: {response.status_code})"

        data = response.json()

        # KOBIS 특이사항: 인증키가 틀려도 200 OK와 함께 faultInfo 객체가 반환됩니다.
        if "faultInfo" in data:
            message = data["faultInfo"].get(
                "message", "인증키 또는 API 요청 오류입니다."
            )
            return None, f"KOBIS API 오류: {message}"

        # 정상 응답 구조 확인
        box_office_result = data.get("boxOfficeResult", {})
        daily_list = box_office_result.get("dailyBoxOfficeList", [])

        # 영화 목록이 비어있는 경우
        if not daily_list:
            return (
                None,
                "해당 날짜의 데이터가 아직 집계되지 않았거나 조회 결과가 없습니다.",
            )

        return daily_list, None

    except requests.exceptions.RequestException as e:
        return None, f"네트워크 통신 중 오류가 발생했습니다: {e}"


# 3. 비밀 금고(st.secrets)에서 API 키 불러오기
# 스트림릿 클라우드의 Secrets 메뉴에 KOBIS_KEY를 설정해야 합니다.
if "KOBIS_KEY" not in st.secrets:
    st.error("🔑 API 인증키가 설정되지 않았습니다.")
    st.info(
        "**확인 안내:**\n"
        "1. Streamlit Cloud의 App Settings -> **Secrets** 메뉴로 이동하세요.\n"
        '2. `KOBIS_KEY = "발급받은키"` 형식으로 비밀키를 입력하고 저장해 주세요.'
    )
    st.stop()

api_key = st.secrets["KOBIS_KEY"]

# 4. 데이터 요청 실행
movies, error_msg = fetch_box_office(api_key, target_dt_param)

# 오류 처리 안내 화면
if error_msg:
    st.error("⚠️ 데이터를 불러오지 못했습니다.")
    st.warning(f"**상세 원인:** {error_msg}")
    st.markdown(
        """
        ---
        ### 💡 확인해 보세요!
        - **KOBIS API 인증키:** Secrets에 등록한 `KOBIS_KEY`가 올바른지 확인해 주세요.
        - **집계 시간:** 자정 직후에는 어제 박스오피스 집계가 진행 중일 수 있습니다. 잠시 후 다시 시도해 주세요.
        - **일일 트래픽:** KOBIS API의 일일 허용 호출량을 초과했는지 확인해 주세요.
        """
    )
    st.stop()

# 5. 데이터 가공 (문자열 -> 숫자 변환)
df = pd.DataFrame(movies)

# 필요한 숫자 컬럼 변환
num_cols = ["rank", "audiCnt", "audiAcc", "scrnCnt"]
for col in num_cols:
    df[col] = pd.to_numeric(df[col], errors="coerce")

# 6. 1위 영화 지표 카드 (Metrics)
top_movie = df.iloc[0]

st.markdown("---")
st.markdown(f"### 🥇 1위 영화: **{top_movie['movieNm']}**")

col1, col2, col3 = st.columns(3)
with col1:
    st.metric(
        label="일일 관객수", value=f"{top_movie['audiCnt']:,} 명"
    )
with col2:
    st.metric(
        label="누적 관객수", value=f"{top_movie['audiAcc']:,} 명"
    )
with col3:
    st.metric(
        label="스크린 수", value=f"{top_movie['scrnCnt']:,} 개"
    )

st.markdown("---")

# 7. 관객수 상위 5편 막대그래프
st.subheader("📊 관객수 상위 5개 영화")
top_5_df = df.head(5).copy()

# 막대그래프 시각화를 위한 데이터 정리
chart_df = top_5_df[["movieNm", "audiCnt"]].set_index("movieNm")
chart_df.columns = ["일일 관객수"]
st.bar_chart(chart_df)

# 8. 전체 순위 표 (Table)
st.subheader("📋 박스오피스 전체 순위 (Top 10)")

# 화면에 보여줄 컬럼 선택 및 이름 변경
display_df = df[
    ["rank", "movieNm", "openDt", "audiCnt", "audiAcc", "scrnCnt"]
].copy()
display_df.columns = [
    "순위",
    "영화명",
    "개봉일",
    "관객수",
    "누적관객",
    "스크린수",
]

# 숫자에 천 단위 쉼표(,) 포맷 적용하여 출력
st.dataframe(
    display_df.style.format(
        {"관객수": "{:,} 명", "누적관객": "{:,} 명", "스크린수": "{:,} 개"}
    ),
    use_container_width=True,
    hide_index=True,
)
