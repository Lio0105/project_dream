import streamlit as st
import json
import requests
import urllib3
from openai import OpenAI

# SSL 경고 메시지 비활성화 (수출입은행 SSL 오류 우회용)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------
# 1. 페이지 및 API 기본 설정
# ---------------------------------------------------------
st.set_page_config(page_title="✈️ 스마트 해외여행 경비 계산 챗봇", page_icon="✈️", layout="centered")

UPSTAGE_API_KEY = "up_Y7OKHBUB2q7pi7C4E1ILIWItBAUOG"
EXIM_AUTH_KEY = "OnS9ZZMNvhJAtIOKWXbF6TDHydWXTL1B"

client = OpenAI(
    api_key=UPSTAGE_API_KEY,
    base_url="https://api.upstage.ai/v1/solar"
)

# ---------------------------------------------------------
# 2. 한국수출입은행 API 기반 실시간 환율 조회 함수
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
# 3. 사용자 대화 맥락 분석 및 국가/통화 추출
# ---------------------------------------------------------
def extract_destination_and_currency(messages_history):
    # 전체 대화 내역 중 최근 대화들을 합쳐 목적지 분석
    full_text = "\n".join([f"{m['role']}: {m['content']}" for m in messages_history])
    
    prompt_extract = f"""
    다음 대화 내역을 확인하여 사용자가 방문하려는 '여행 국가/도시'와 '사용할 주요 통화코드(USD, JPY, EUR, THB, TWD, VND 등)'를 JSON으로 추출해줘.
    만약 대화 내용에서 국가가 아직 확실하지 않다면 '해외', 'USD'로 반환해줘.
    
    예시: {{"country": "일본 도쿄", "currency": "JPY"}}
    
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
        country = extracted.get("country", "해외")
        currency = extracted.get("currency", "USD").upper()
    except Exception:
        country = "해외"
        currency = "USD"
        
    return country, currency

# ---------------------------------------------------------
# 4. 멀티턴 대화 기반 여행 경비 컨설팅 챗봇 엔진
# ---------------------------------------------------------
def generate_travel_consulting_response(messages_history):
    # 목적지 및 통화 파악
    country, currency = extract_destination_and_currency(messages_history)
    rate = get_exchange_rate(currency)

    system_prompt = f"""
    당신은 친절하고 정밀한 '해외여행 전문 컨설턴트 챗봇'입니다.
    사용자와 대화를 나누며 필요한 여행 세부 정보를 파악하고, 최신 환율 정보를 기반으로 세밀한 여행 경비를 산출해 드립니다.

    [현재 조회된 실시간 환율 정보]
    - 목적지/통화: {country} ({currency})
    - 한국수출입은행 기준 환율: 1 {currency} = {rate:,.2f} 원 (KRW)

    [대화 및 답변 작성 지침]
    1. 사용자의 입력에서 아래 핵심 항목 중 빠진 부분이 있다면 자연스럽게 질문하여 추가 정보를 파악하세요:
       - 여행 목적지 및 총 일정 (며칠)
       - 총 인원수
       - 항공권 스타일 (저가항공/국적기, 직항/경유 등)
       - 숙소 등급 (게스트하우스/가성비 호텔/고급 리조트 등)
       - 주요 일정/액티비티 (쇼핑 위주, 디즈니랜드, 힐링 등)

    2. 여행 정보가 어느 정도 수집되었거나 계산 요청을 받으면, 견적을 산출해 주세요:
       - **핵심 요구사항**: 비용 계산 시 단순 단일 금액이 아닌 **"약 OO만 원 ~ OO만 원 이상"** 형태의 **범위(Min~Max)**를 명시하세요.
       - **원화(KRW) 및 현지 통화({currency}) 금액**을 함께 병기해 주세요.
       - 항공, 숙박, 식비/카페, 교통/관광, 비상금/기타 항목별 예상 범위를 세부적으로 제시하세요.
       - 마지막에는 1인당 예상 비용과 전체 인원의 총예상 경비를 정리해 주세요.

    3. 말투는 밝고 친근하며 전문적인 톤을 유지해 주세요.
    """

    # Upstage API는 system 프로필과 전체 대화 히스토리를 받아서 전달
    api_messages = [{"role": "system", "content": system_prompt}]
    for msg in messages_history:
        api_messages.append({"role": msg["role"], "content": msg["content"]})

    response = client.chat.completions.create(
        model="solar-pro",
        messages=api_messages
    )

    return response.choices[0].message.content

# ---------------------------------------------------------
# 5. Streamlit UI 및 상태 관리
# ---------------------------------------------------------
st.title("✈️ 정밀 여행 경비 계산 컨설팅 챗봇")
st.caption("한국수출입은행의 실시간 환율을 반영하며, 대화를 통해 조건에 맞는 여행 경비 범위를 정확히 계산합니다.")

# 대화 기록 세션 관리
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "안녕하세요! 해외 여행 계획을 세우고 계시군요. ✈️\n\n어디로 떠나실 예정이신가요? **'어느 나라/도시인지, 며칠 동안 가시는지, 몇 명이서 가시는지'** 말씀해 주시면 자세히 견적을 맞춰 드릴게요!"}
    ]

# 이전 대화 내용 화면에 출력
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 사용자 대화 입력 처리
if prompt := st.chat_input("여행 도시, 기간, 인원, 선호 스타일 등을 자유롭게 말해 보세요..."):
    # 1. 사용자 입력 메시지 표시 및 기록
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    # 2. AI 답변 생성 중 로딩 상태 표시
    with st.chat_message("assistant"):
        with st.spinner("대화 내용 및 실시간 환율 분석 중..."):
            answer = generate_travel_consulting_response(st.session_state.messages)
            st.markdown(answer)
    
    # 3. AI 답변 기록
    st.session_state.messages.append({"role": "assistant", "content": answer})