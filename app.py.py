import streamlit as st
import json
import requests
import urllib3
import datetime
import pandas as pd
import plotly.express as px
from openai import OpenAI

# SSL 경고 메시지 비활성화
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------
# 1. 페이지 및 API 기본 설정
# ---------------------------------------------------------
st.set_page_config(page_title="✈️ 스마트 해외여행 경비 & 일정 통합 컨설팅", page_icon="✈️", layout="wide")

UPSTAGE_API_KEY = "up_Y7OKHBUB2q7pi7C4E1ILIWItBAUOG"
EXIM_AUTH_KEY = "OnS9ZZMNvhJAtIOKWXbF6TDHydWXTL1B"
OWM_API_KEY = "93cc316fee1e1cf074a205add809d49e"

client = OpenAI(
    api_key=UPSTAGE_API_KEY,
    base_url="https://api.upstage.ai/v1/solar"
)

# ---------------------------------------------------------
# 2. 대화 내역에서 목적지, 통화, 영어 도시명 추출
# ---------------------------------------------------------
def extract_destination_info(messages_history):
    full_text = "\n".join([f"{m['role']}: {m['content']}" for m in messages_history if m['role'] != 'system'])
    
    prompt_extract = f"""
    다음 대화 내역을 읽고 사용자가 가려는 '여행 국가/도시명', '해당 도시의 영문명(OpenWeatherMap API용)', '주요 통화코드(USD, JPY, EUR, THB, TWD, VND 등)', '한글 통화명(달러, 엔, 유로, 바트, 대만 달러, 동 등)'을 JSON으로 추출해줘.
    사용자가 어디로 갈지 도시나 국가를 명확히 말하지 않았다면 country를 "미정"으로 반환해줘.
    
    예시: {{"country": "일본 도쿄", "city_en": "Tokyo", "currency": "JPY", "currency_kor": "엔"}}
    
    대화 내역:
    {full_text}
    """

    try:
        res = client.chat.completions.create(
            model="solar-pro",
            messages=[{"role": "user", "content": prompt_extract}],
            response_format={"type": "json_object"}
        )
        extracted = json.loads(res.choices[0].message.content)
        return (
            extracted.get("country", "미정"),
            extracted.get("city_en", "Tokyo"),
            extracted.get("currency", "JPY").upper(),
            extracted.get("currency_kor", "엔")
        )
    except Exception:
        return ("미정", "Tokyo", "JPY", "엔")

# ---------------------------------------------------------
# 3. OpenWeatherMap API 및 선택 기간 기반 날씨 조회
# ---------------------------------------------------------
def get_weather_info(city_en: str, start_date, end_date) -> str:
    current_url = f"https://api.openweathermap.org/data/2.5/weather?q={city_en}&appid={OWM_API_KEY}&units=metric&lang=kr"
    date_str = f"[{start_date.strftime('%Y/%m/%d')} ~ {end_date.strftime('%Y/%m/%d')}]"
    
    try:
        res_curr = requests.get(current_url, timeout=5).json()
        if res_curr.get("cod") == 200:
            temp_curr = res_curr['main']['temp']
            desc_curr = res_curr['weather'][0]['description']
            humidity = res_curr['main']['humidity']
            return f"선택 일정 {date_str} 현지 현재 상태: {desc_curr} ({temp_curr:.1f}°C, 습도 {humidity}%)"
        else:
            return f"선택 일정 {date_str}: 현지 기후 데이터를 기반으로 옷차림과 우산을 준비해 주세요."
    except Exception as e:
        print(f"날씨 API 예외 발생: {e}")
        return f"선택 일정 {date_str}: 날씨 정보를 불러오는 중입니다."

# ---------------------------------------------------------
# 4. 한국수출입은행 API 기반 실시간 환율 조회
# ---------------------------------------------------------
def get_exchange_rate(target_currency: str) -> float:
    target_currency = target_currency.upper()
    
    url = "https://www.koreaexim.go.kr/site/program/financial/exchangeJSON"
    params = {
        "authkey": EXIM_AUTH_KEY,
        "searchdate": "",
        "data": "AP01"
    }

    try:
        response = requests.get(url, params=params, timeout=5, verify=False)
        data = response.json()
        
        if data:
            for item in data:
                if target_currency in item["cur_unit"]:
                    rate_str = item["deal_bas_r"].replace(",", "")
                    rate = float(rate_str)
                    
                    if "100" in item["cur_unit"]:
                        rate = rate / 100.0
                        
                    return rate
    except Exception as e:
        print(f"수출입은행 API 예외 발생: {e}")

    fallback_rates = {
        "USD": 1350.0,
        "JPY": 9.1,
        "EUR": 1470.0,
        "THB": 37.0,
        "TWD": 42.0,
        "VND": 0.055
    }
    return fallback_rates.get(target_currency, 1350.0)

# ---------------------------------------------------------
# 5. 일자별 추천 여행 코스 생성
# ---------------------------------------------------------
def generate_itinerary_text(destination_city, days):
    prompt = f"""
    {destination_city} {days}박 {days+1}일 여행에 적합한 지역 맞춤형 추천 일정표를 작성해줘.
    사용자가 직접 읽고 쉽게 편집할 수 있도록 불릿 포인트 텍스트 형식으로 작성해줘.
    """
    try:
        res = client.chat.completions.create(
            model="solar-pro",
            messages=[{"role": "user", "content": prompt}]
        )
        return res.choices[0].message.content
    except Exception as e:
        print(f"일정 생성 오류: {e}")
        return "일정을 불러오는 중 오류가 발생했습니다. 직접 코스를 입력해 보세요!"

# ---------------------------------------------------------
# 6. 사이드바 설정
# ---------------------------------------------------------
st.sidebar.title("⚙️ 여행 세부 조건 설정")
st.sidebar.caption("여행 기간과 인원을 설정하세요.")

st.sidebar.subheader("📅 여행 일정 선택")

today = datetime.date.today()
default_start = today + datetime.timedelta(days=7)
default_end = default_start + datetime.timedelta(days=3)

col_start, col_end = st.sidebar.columns(2)

with col_start:
    start_date = st.date_input("🛫 출발일", value=default_start, format="YYYY/MM/DD")

with col_end:
    end_date = st.date_input("🛬 도착일", value=default_end, format="YYYY/MM/DD")

if end_date <= start_date:
    end_date = start_date + datetime.timedelta(days=1)

travel_days = (end_date - start_date).days
travel_nights = travel_days
travel_full_days = travel_days + 1

st.sidebar.info(f"🗓️ **선택 일정:** {start_date.strftime('%Y/%m/%d')} ~ {end_date.strftime('%Y/%m/%d')} ({travel_nights}박 {travel_full_days}일)")

travel_members = st.sidebar.number_input("여행 인원 (명)", min_value=1, max_value=20, value=2)
flight_class = st.sidebar.radio("항공권 등급", ["LCC (저가항공)", "FSC (일반 국적기)", "비즈니스석"])
hotel_type = st.sidebar.radio("숙소 등급", ["게스트하우스/호스텔", "3성급 (가성비 호텔)", "4~5성급 (고급 호텔/리조트)"])

if st.sidebar.button("🔄 대화 내용 초기화"):
    st.session_state.messages = []
    for key in ['current_dest', 'custom_itinerary', 'cost_data']:
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()

# ---------------------------------------------------------
# 7. 정밀 수치 산정 챗봇 엔진 (JSON 기반 규격화)
# ---------------------------------------------------------
def generate_travel_consulting_response(messages_history):
    destination, city_en, current_currency, currency_kor_name = extract_destination_info(messages_history)
    
    if destination == "미정":
        return "안녕하세요! ✈️ 어느 나라나 도시로 떠나실 예정이신가요? 가고 싶으신 곳을 편하게 말씀해 주세요!", "미정"

    rate = get_exchange_rate(current_currency)
    weather_summary = get_weather_info(city_en, start_date, end_date)

    # 1인 기준 하루 적정 식비 가이드
    suggested_food_min = travel_members * travel_full_days * 30000
    suggested_food_max = travel_members * travel_full_days * 60000

    system_prompt = f"""
    당신은 해외여행 경비 산정 전문 컨설턴트입니다.
    사용자의 입력과 조건을 바탕으로 '현실적이고 정확한 경비 데이터'를 JSON 규격으로 작성해야 합니다.

    [조건]
    - 목적지: {destination}
    - 기간: {travel_nights}박 {travel_full_days}일 (총 {travel_full_days}일)
    - 인원: {travel_members}명 (모든 금액은 {travel_members}명 전체 기준 총액)
    - 항공 등급: {flight_class}
    - 숙소 등급: {hotel_type}
    - 환율: 1 {currency_kor_name} = {rate:.2f} 원

    [단가 가이드 라인 (KRW 기준 총액)]
    1. 항공료 ({travel_members}명 왕복 총액): {flight_class} 수준 반영
    2. 숙박비 ({travel_nights}박 총액): {hotel_type} 수준 반영
    3. 식비 ({travel_members}명 {travel_full_days}일 총액): 권장액 범위 약 {suggested_food_min:,}원 ~ {suggested_food_max:,}원 사이
    4. 교통비 ({travel_members}명 총액): 현지 대중교통 및 이동 비용
    5. 액티비티 ({travel_members}명 총액): 입장료 및 체험비
    6. 비상금: 상기 1~5번 항목 최소/최대 합계의 약 10%

    반드시 아래 JSON 형식으로만 응답하세요:
    {{
        "flight_min": 숫자, "flight_max": 숫자,
        "hotel_min": 숫자, "hotel_max": 숫자,
        "food_min": 숫자, "food_max": 숫자,
        "transport_min": 숫자, "transport_max": 숫자,
        "activity_min": 숫자, "activity_max": 숫자,
        "extra_min": 숫자, "extra_max": 숫자,
        "advice": "날씨 및 여행 팁 2~3줄 요약"
    }}
    """

    try:
        res = client.chat.completions.create(
            model="solar-pro",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": "경비 산정해줘"}]
        )
        data = json.loads(res.choices[0].message.content)
    except Exception as e:
        print(f"LLM JSON 생성 오류: {e}")
        data = {
            "flight_min": 400000, "flight_max": 600000,
            "hotel_min": 300000, "hotel_max": 450000,
            "food_min": suggested_food_min, "food_max": suggested_food_max,
            "transport_min": 100000, "transport_max": 150000,
            "activity_min": 100000, "activity_max": 200000,
            "extra_min": 120000, "extra_max": 180000,
            "advice": "우산과 우비를 꼭 챙기시고 실내 관람 위주로 일정을 계획하세요!"
        }

    # 세션 상태에 경비 데이터 저장 (차트 즉시 반영용)
    st.session_state['cost_data'] = data

    # 최소/최대 총합 계산
    total_min = sum([data['flight_min'], data['hotel_min'], data['food_min'], data['transport_min'], data['activity_min'], data['extra_min']])
    total_max = sum([data['flight_max'], data['hotel_max'], data['food_max'], data['transport_max'], data['activity_max'], data['extra_max']])

    # 엔화 등은 100엔 단위 반올림하여 깔끔하게 표시
    def to_curr(krw_val):
        val = krw_val / rate
        if current_currency == "JPY":
            val = round(val, -2)
        else:
            val = round(val)
        return f"{int(val):,} {currency_kor_name}"

    formatted_response = f"""
### 🗓️ **{destination} 여행 개요**
* **일정**: {start_date.strftime('%Y/%m/%d')} ~ {end_date.strftime('%Y/%m/%d')} ({travel_nights}박 {travel_full_days}일)
* **인원**: {travel_members}명
* **날씨 안내**: {weather_summary}

---

### 💼 **예상 경비 내역 (전체 총액, {travel_members}인 기준)**

| 항목 | 원화 (KRW) | {currency_kor_name} ({current_currency}) |
| :--- | :--- | :--- |
| **항공료** | {data['flight_min']:,} ~ {data['flight_max']:,}원 | {to_curr(data['flight_min'])} ~ {to_curr(data['flight_max'])} |
| **숙박비** | {data['hotel_min']:,} ~ {data['hotel_max']:,}원 | {to_curr(data['hotel_min'])} ~ {to_curr(data['hotel_max'])} |
| **식비** | {data['food_min']:,} ~ {data['food_max']:,}원 | {to_curr(data['food_min'])} ~ {to_curr(data['food_max'])} |
| **교통비** | {data['transport_min']:,} ~ {data['transport_max']:,}원 | {to_curr(data['transport_min'])} ~ {to_curr(data['transport_max'])} |
| **액티비티** | {data['activity_min']:,} ~ {data['activity_max']:,}원 | {to_curr(data['activity_min'])} ~ {to_curr(data['activity_max'])} |
| **비상금** | {data['extra_min']:,} ~ {data['extra_max']:,}원 | {to_curr(data['extra_min'])} ~ {to_curr(data['extra_max'])} |
| **총 예상 비용** | **{total_min:,} ~ {total_max:,}원** | **{to_curr(total_min)} ~ {to_curr(total_max)}** |

---

### 📌 **여행 팁 & 참고사항**
* {data['advice']}
    """
    return formatted_response, destination

# ---------------------------------------------------------
# 8. 메인 UI
# ---------------------------------------------------------
st.title("✈️ 정밀 여행 경비 & 일정 통합 컨설팅")
st.caption("한국수출입은행 실시간 환율과 지정 기간 현지 날씨 데이터를 기반으로 최적의 경비와 코스를 안내합니다.")

if "messages" not in st.session_state or len(st.session_state.messages) == 0:
    st.session_state.messages = [
        {"role": "assistant", "content": "안녕하세요! ✈️ 어느 나라나 도시로 떠나실 예정이신가요?\n\n채팅으로 **'도쿄 3박 4일'**, **'방콕 맛집 여행'**처럼 가고 싶으신 곳을 편하게 말씀해 주세요!"}
    ]

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("여행지나 추가 요구사항을 입력하세요..."):
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        with st.spinner("목적지 분석 및 정밀 경비 산정 중..."):
            answer, detected_dest = generate_travel_consulting_response(st.session_state.messages)
            st.markdown(answer)
            if detected_dest != "미정":
                st.session_state['current_dest'] = detected_dest
    
    st.session_state.messages.append({"role": "assistant", "content": answer})

current_dest = st.session_state.get('current_dest', None)

# ---------------------------------------------------------
# 9. 하단 보조 영역 (표의 계산 수치와 100% 일치하는 동적 파이차트)
# ---------------------------------------------------------
if current_dest and current_dest != "미정":
    st.markdown("---")
    st.success(f"📍 **[{current_dest}]** ({start_date.strftime('%Y/%m/%d')} ~ {end_date.strftime('%Y/%m/%d')}) 여행 맞춤 분석 및 일정 코스")
    
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("📊 항목별 예상 경비 비중")
        
        cost_data = st.session_state.get('cost_data', {})
        if cost_data:
            avg_flight = (cost_data.get('flight_min', 0) + cost_data.get('flight_max', 0)) / 2
            avg_hotel = (cost_data.get('hotel_min', 0) + cost_data.get('hotel_max', 0)) / 2
            avg_food = (cost_data.get('food_min', 0) + cost_data.get('food_max', 0)) / 2
            
            avg_transport = (cost_data.get('transport_min', 0) + cost_data.get('transport_max', 0)) / 2
            avg_activity = (cost_data.get('activity_min', 0) + cost_data.get('activity_max', 0)) / 2
            avg_extra = (cost_data.get('extra_min', 0) + cost_data.get('extra_max', 0)) / 2
            
            avg_etc = avg_transport + avg_activity + avg_extra

            df_pie = pd.DataFrame({
                '항목': ['항공권', '숙박비', '식비/카페', '교통/액티비티/비상금'],
                '금액': [avg_flight, avg_hotel, avg_food, avg_etc]
            })
        else:
            df_pie = pd.DataFrame({
                '항목': ['항공권', '숙박비', '식비/카페', '교통/액티비티/비상금'],
                '금액': [35, 25, 20, 20]
            })

        fig = px.pie(
            df_pie, 
            values='금액', 
            names='항목', 
            hole=0.3,
            color_discrete_sequence=px.colors.qualitative.Pastel
        )
        fig.update_traces(textposition='inside', textinfo='percent+label')
        fig.update_layout(showlegend=False, margin=dict(t=20, b=20, l=20, r=20))
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader(f"🗺️ [{current_dest}] 일자별 핵심 코스")
        
        if st.button("✨ AI 추천 코스 불러오기"):
            with st.spinner(f"{current_dest} 맞춤 코스 생성 중..."):
                generated_text = generate_itinerary_text(current_dest, travel_days)
                st.session_state['custom_itinerary'] = generated_text

        default_itinerary_text = st.session_state.get(
            'custom_itinerary', 
            f"위 [✨ AI 추천 코스 불러오기] 버튼을 누르시거나, 여기에 직접 일정을 자유롭게 작성해 보세요!\n\n📍 Day 1: {current_dest} 도착\n- "
        )
        
        user_edited_itinerary = st.text_area(
            "나만의 코스 작성 및 수정",
            value=default_itinerary_text,
            height=280
        )
        st.session_state['custom_itinerary'] = user_edited_itinerary

    # ---------------------------------------------------------
    # 10. 파일 다운로드
    # ---------------------------------------------------------
    st.markdown("---")
    download_text = f"=== {current_dest} 여행 경비 견적서 및 코스 ===\n"
    download_text += f"- 기간: {start_date.strftime('%Y/%m/%d')} ~ {end_date.strftime('%Y/%m/%d')} ({travel_nights}박 {travel_full_days}일) / 인원: {travel_members}명\n"
    download_text += f"- 항공/숙소 스타일: {flight_class} / {hotel_type}\n"
    download_text += "=" * 40 + "\n\n"

    download_text += "[일자별 추천/작성 코스]\n"
    download_text += st.session_state.get('custom_itinerary', '코스 미작성') + "\n\n"

    st.download_button(
        label="📄 전체 여행 견적서 및 일시 코스(.txt) 다운로드",
        data=download_text,
        file_name=f"{current_dest}_여행_견적서_및_코스.txt",
        mime="text/plain"
    )
