import streamlit as st
import json
import requests
import urllib3
import datetime
import io
import os
import pandas as pd
from openai import OpenAI

# PDF 생성을 위한 reportlab 라이브러리 및 폰트 설정
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# SSL 경고 메시지 비활성화
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------
# 한글 폰트 등록 (NanumGothic)
# ---------------------------------------------------------
FONT_NAME = "NanumGothic"

def register_korean_font():
    font_path = "NanumGothic.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
        try:
            r = requests.get(url, timeout=10)
            with open(font_path, "wb") as f:
                f.write(r.content)
        except Exception as e:
            print(f"폰트 다운로드 실패: {e}")
            
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont(FONT_NAME, font_path))
        return FONT_NAME
    return "Helvetica"

font_to_use = register_korean_font()

# ---------------------------------------------------------
# 1. 페이지 및 API 기본 설정
# ---------------------------------------------------------
st.set_page_config(page_title="Upstage Solar - 여행 경비 계산 AI 챗봇", page_icon="☀️", layout="wide")

UPSTAGE_API_KEY = "up_Y7OKHBUB2q7pi7C4E1ILIWItBAUOG"
EXIM_AUTH_KEY = "OnS9ZZMNvhJAtIOKWXbF6TDHydWXTL1B"
OWM_API_KEY = "93cc316fee1e1cf074a205add809d49e"

client = OpenAI(
    api_key=UPSTAGE_API_KEY,
    base_url="https://api.upstage.ai/v1/solar"
)

# 세션 기본값 초기화
if "start_date" not in st.session_state:
    st.session_state.start_date = datetime.date.today() + datetime.timedelta(days=7)
if "end_date" not in st.session_state:
    st.session_state.end_date = st.session_state.start_date + datetime.timedelta(days=3)
if "travel_members" not in st.session_state:
    st.session_state.travel_members = 2
if "flight_class" not in st.session_state:
    st.session_state.flight_class = "LCC (저가항공)"
if "hotel_type" not in st.session_state:
    st.session_state.hotel_type = "3성급 (가성비 호텔)"

# ---------------------------------------------------------
# 2. 유틸리티 및 API 함수들
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

def get_exchange_rate(target_currency: str) -> float:
    target_currency = target_currency.upper()
    url = "https://www.koreaexim.go.kr/site/program/financial/exchangeJSON"
    params = {"authkey": EXIM_AUTH_KEY, "searchdate": "", "data": "AP01"}

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

    fallback_rates = {"USD": 1350.0, "JPY": 9.1, "EUR": 1470.0, "THB": 37.0, "TWD": 42.0, "VND": 0.055}
    return fallback_rates.get(target_currency, 1350.0)

def generate_itinerary_text(destination_city, days):
    prompt = f"""
    {destination_city} {days}박 {days+1}일 여행에 적합한 추천 일정표를 작성해줘.

    [작성 규칙]
    1. 별표 문자는 절대 사용하지 말 것. (볼드체 강조 표현 완전히 금지)
    2. 지명, 맛집, 관광지 이름은 실제로 존재하는 정확한 명칭만 사용할 것.
    3. 시간대와 활동이 현실적이어야 함 (낮 시간 야경 투어 금지).
    4. 대시(-) 및 일반 텍스트만 사용하여 깔끔하게 작성할 것.
    """
    try:
        res = client.chat.completions.create(
            model="solar-pro",
            messages=[{"role": "user", "content": prompt}]
        )
        content = res.choices[0].message.content
        return content.replace("*", "")
    except Exception as e:
        print(f"일정 생성 오류: {e}")
        return "일정을 불러오는 중 오류가 발생했습니다."

def generate_travel_consulting_response(messages_history):
    destination, city_en, current_currency, currency_kor_name = extract_destination_info(messages_history)
    
    if destination == "미정":
        return "안녕하세요! ✈️ 어느 나라나 도시로 떠나실 예정이신가요? 가고 싶으신 곳을 편하게 말씀해 주세요!", "미정"

    start_d = st.session_state.start_date
    end_d = st.session_state.end_date
    t_members = st.session_state.travel_members
    f_class = st.session_state.flight_class
    h_type = st.session_state.hotel_type

    t_days = (end_d - start_d).days
    t_nights = t_days
    t_full_days = t_days + 1

    rate = get_exchange_rate(current_currency)
    weather_summary = get_weather_info(city_en, start_d, end_d)

    suggested_food_min = t_members * t_full_days * 30000
    suggested_food_max = t_members * t_full_days * 60000

    system_prompt = f"""
    당신은 해외여행 경비 산정 전문 컨설턴트입니다.
    사용자의 입력과 조건을 바탕으로 '현실적이고 정확한 경비 데이터'를 JSON 규격으로 작성해야 합니다.

    [조건]
    - 목적지: {destination}
    - 기간: {t_nights}박 {t_full_days}일 (총 {t_full_days}일)
    - 인원: {t_members}명 (모든 금액은 {t_members}명 전체 기준 총액)
    - 항공 등급: {f_class}
    - 숙소 등급: {h_type}
    - 환율: 1 {currency_kor_name} = {rate:.2f} 원

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

    st.session_state['cost_data'] = data
    st.session_state['currency_info'] = (current_currency, currency_kor_name, rate)

    total_min = sum([data['flight_min'], data['hotel_min'], data['food_min'], data['transport_min'], data['activity_min'], data['extra_min']])
    total_max = sum([data['flight_max'], data['hotel_max'], data['food_max'], data['transport_max'], data['activity_max'], data['extra_max']])

    def to_curr(krw_val):
        val = krw_val / rate
        if current_currency == "JPY":
            val = round(val, -2)
        else:
            val = round(val)
        return f"{int(val):,} {currency_kor_name}"

    formatted_response = f"""
### 🗓️ {destination} 여행 개요
- 일정: {start_d.strftime('%Y/%m/%d')} ~ {end_d.strftime('%Y/%m/%d')} ({t_nights}박 {t_full_days}일)
- 인원: {t_members}명
- 날씨 안내: {weather_summary}

---

### 💼 예상 경비 내역 (전체 총액, {t_members}인 기준)

| 항목 | 원화 (KRW) | {currency_kor_name} ({current_currency}) |
| :--- | :--- | :--- |
| 항공료 | {data['flight_min']:,} ~ {data['flight_max']:,}원 | {to_curr(data['flight_min'])} ~ {to_curr(data['flight_max'])} |
| 숙박비 | {data['hotel_min']:,} ~ {data['hotel_max']:,}원 | {to_curr(data['hotel_min'])} ~ {to_curr(data['hotel_max'])} |
| 식비 | {data['food_min']:,} ~ {data['food_max']:,}원 | {to_curr(data['food_min'])} ~ {to_curr(data['food_max'])} |
| 교통비 | {data['transport_min']:,} ~ {data['transport_max']:,}원 | {to_curr(data['transport_min'])} ~ {to_curr(data['transport_max'])} |
| 액티비티 | {data['activity_min']:,} ~ {data['activity_max']:,}원 | {to_curr(data['activity_min'])} ~ {to_curr(data['activity_max'])} |
| 비상금 | {data['extra_min']:,} ~ {data['extra_max']:,}원 | {to_curr(data['extra_min'])} ~ {to_curr(data['extra_max'])} |
| 총 예상 비용 | {total_min:,} ~ {total_max:,}원 | {to_curr(total_min)} ~ {to_curr(total_max)} |

---

### 📌 여행 팁 & 참고사항
- {data['advice']}
    """
    return formatted_response, destination

# ---------------------------------------------------------
# 모던 한글 PDF 생성 함수
# ---------------------------------------------------------
def generate_pdf_bytes(dest, start_date, end_date, members, cost_data, itinerary_text):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=letter,
        rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40
    )
    
    styles = getSampleStyleSheet()
    
    PRIMARY_COLOR = colors.HexColor("#1E293B")
    ACCENT_COLOR = colors.HexColor("#2563EB")
    BG_LIGHT = colors.HexColor("#F8FAFC")
    TEXT_DARK = colors.HexColor("#334155")

    title_style = ParagraphStyle(
        'CustomTitle',
        fontName=font_to_use,
        fontSize=22,
        leading=26,
        textColor=PRIMARY_COLOR,
        spaceAfter=6
    )
    
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        fontName=font_to_use,
        fontSize=11,
        leading=15,
        textColor=TEXT_DARK,
        spaceAfter=15
    )

    section_heading = ParagraphStyle(
        'SectionHeading',
        fontName=font_to_use,
        fontSize=14,
        leading=18,
        textColor=ACCENT_COLOR,
        spaceBefore=12,
        spaceAfter=8
    )

    body_style = ParagraphStyle(
        'CustomBody',
        fontName=font_to_use,
        fontSize=9.5,
        leading=14,
        textColor=TEXT_DARK
    )

    table_header_style = ParagraphStyle(
        'TableHeader',
        fontName=font_to_use,
        fontSize=10,
        leading=12,
        textColor=colors.whitesmoke,
        alignment=1
    )

    table_cell_style = ParagraphStyle(
        'TableCell',
        fontName=font_to_use,
        fontSize=9,
        leading=12,
        textColor=TEXT_DARK,
        alignment=1
    )

    elements = []

    elements.append(Paragraph(f"<b>{dest} 여행 경비 견적 및 일정표</b>", title_style))
    
    t_days = (end_date - start_date).days
    info_str = f"<b>여행 기간:</b> {start_date.strftime('%Y년 %m월 %d일')} ~ {end_date.strftime('%Y년 %m월 %d일')} ({t_days}박 {t_days+1}일) &nbsp;|&nbsp; <b>인원:</b> {members}명"
    elements.append(Paragraph(info_str, subtitle_style))
    
    elements.append(HRFlowable(width="100%", thickness=1.5, color=ACCENT_COLOR, spaceBefore=0, spaceAfter=15))

    if cost_data:
        elements.append(Paragraph("<b>💰 예상 경비 세부 내역</b>", section_heading))
        
        table_data = [
            [
                Paragraph("<b>항목</b>", table_header_style), 
                Paragraph("<b>최소 경비 (원)</b>", table_header_style), 
                Paragraph("<b>최대 경비 (원)</b>", table_header_style)
            ],
            [Paragraph("항공료", table_cell_style), Paragraph(f"{cost_data.get('flight_min',0):,} 원", table_cell_style), Paragraph(f"{cost_data.get('flight_max',0):,} 원", table_cell_style)],
            [Paragraph("숙박비", table_cell_style), Paragraph(f"{cost_data.get('hotel_min',0):,} 원", table_cell_style), Paragraph(f"{cost_data.get('hotel_max',0):,} 원", table_cell_style)],
            [Paragraph("식비", table_cell_style), Paragraph(f"{cost_data.get('food_min',0):,} 원", table_cell_style), Paragraph(f"{cost_data.get('food_max',0):,} 원", table_cell_style)],
            [Paragraph("교통비", table_cell_style), Paragraph(f"{cost_data.get('transport_min',0):,} 원", table_cell_style), Paragraph(f"{cost_data.get('transport_max',0):,} 원", table_cell_style)],
            [Paragraph("액티비티", table_cell_style), Paragraph(f"{cost_data.get('activity_min',0):,} 원", table_cell_style), Paragraph(f"{cost_data.get('activity_max',0):,} 원", table_cell_style)],
            [Paragraph("비상금", table_cell_style), Paragraph(f"{cost_data.get('extra_min',0):,} 원", table_cell_style), Paragraph(f"{cost_data.get('extra_max',0):,} 원", table_cell_style)],
        ]
        
        tot_min = sum([cost_data.get(k, 0) for k in ['flight_min', 'hotel_min', 'food_min', 'transport_min', 'activity_min', 'extra_min']])
        tot_max = sum([cost_data.get(k, 0) for k in ['flight_max', 'hotel_max', 'food_max', 'transport_max', 'activity_max', 'extra_max']])
        
        total_header_style = ParagraphStyle('TotH', parent=table_header_style, textColor=PRIMARY_COLOR)
        table_data.append([
            Paragraph("<b>총 예상 비용</b>", total_header_style),
            Paragraph(f"<b>{tot_min:,} 원</b>", total_header_style),
            Paragraph(f"<b>{tot_max:,} 원</b>", total_header_style)
        ])

        t = Table(table_data, colWidths=[160, 180, 180])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), PRIMARY_COLOR),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,0), 6),
            ('TOPPADDING', (0,0), (-1,0), 6),
            ('GRID', (0,0), (-1,-2), 0.5, colors.HexColor("#CBD5E1")),
            ('ROWBACKGROUNDS', (0,1), (-1,-2), [colors.white, BG_LIGHT]),
            ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#E2E8F0")),
            ('LINEABOVE', (0,-1), (-1,-1), 1.5, PRIMARY_COLOR),
            ('BOTTOMPADDING', (0,-1), (-1,-1), 8),
            ('TOPPADDING', (0,-1), (-1,-1), 8),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 15))

    elements.append(Paragraph("<b>🗺️ 추천 여행 코스 및 일정</b>", section_heading))
    
    clean_itinerary = itinerary_text.replace('*', '').replace('\n', '<br/>')
    elements.append(Paragraph(clean_itinerary, body_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()

# ---------------------------------------------------------
# 3. 메인 레이아웃 및 상단 타이틀
# ---------------------------------------------------------
st.title("☀️ Upstage Solar - 여행 경비 계산 AI 챗봇")
st.caption("실시간 환율 API와 Upstage Solar AI 모델을 연동하여 맞춤형 여행 경비를 원화(KRW) 및 현지 통화로 정밀하게 계산해 드립니다.")

# ---------------------------------------------------------
# 4. 상단 탭 (그래프 탭 완전히 삭제 -> 3개 탭 구성)
# ---------------------------------------------------------
tab1, tab2, tab3 = st.tabs([
    "💬 Solar AI 대화형 질의", 
    "🗺️ 여행 코스 편집", 
    "🎛️ 수동 상세 설정"
])

# ---------------------------------------------------------
# TAB 1: Solar AI 대화형 질의 (메인 챗봇)
# ---------------------------------------------------------
with tab1:
    if "messages" not in st.session_state or len(st.session_state.messages) == 0:
        st.session_state.messages = [
            {"role": "assistant", "content": "안녕하세요! ✈️ 어느 나라나 도시로 떠나실 예정이신가요?\n\n채팅으로 '도쿄 3박 4일', '방콕 맛집 여행'처럼 가고 싶으신 곳을 편하게 말씀해 주세요!"}
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

    if current_dest and current_dest != "미정":
        st.success(f"📍 목적지 [{current_dest}] 분석 완료! 상단 '🗺️ 여행 코스 편집' 탭에서 코스를 확인하세요.")

# ---------------------------------------------------------
# TAB 2: 여행 코스 편집 및 PDF 다운로드
# ---------------------------------------------------------
with tab2:
    current_dest = st.session_state.get('current_dest', None)
    if current_dest and current_dest != "미정":
        st.subheader(f"🗺️ [{current_dest}] 일자별 추천 코스 작성 & 내보내기")
        
        travel_days = (st.session_state.end_date - st.session_state.start_date).days
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
            value=default_itinerary_text.replace("*", ""),
            height=300
        )
        st.session_state['custom_itinerary'] = user_edited_itinerary

        st.markdown("---")
        st.subheader("📥 견적서 & 코스 저장")
        
        col_dl1, col_dl2 = st.columns(2)
        
        with col_dl1:
            download_text = f"=== {current_dest} 여행 경비 견적서 및 코스 ===\n"
            download_text += f"- 기간: {st.session_state.start_date.strftime('%Y/%m/%d')} ~ {st.session_state.end_date.strftime('%Y/%m/%d')} / 인원: {st.session_state.travel_members}명\n\n"
            download_text += st.session_state.get('custom_itinerary', '코스 미작성').replace("*", "")

            st.download_button(
                label="📄 텍스트 파일 (.txt) 다운로드",
                data=download_text,
                file_name=f"{current_dest}_여행_견적서.txt",
                mime="text/plain",
                use_container_width=True
            )

        with col_dl2:
            pdf_data = generate_pdf_bytes(
                current_dest, 
                st.session_state.start_date, 
                st.session_state.end_date, 
                st.session_state.travel_members, 
                st.session_state.get('cost_data', {}), 
                st.session_state.get('custom_itinerary', '').replace("*", "")
            )
            
            st.download_button(
                label="📕 PDF 문서 (.pdf) 다운로드",
                data=pdf_data,
                file_name=f"{current_dest}_여행_견적서.pdf",
                mime="application/pdf",
                use_container_width=True
            )
    else:
        st.info("💡 대화 창에서 목적지를 입력하시면 맞춤 일정 코스가 생성됩니다.")

# ---------------------------------------------------------
# TAB 3: 수동 상세 설정 (인원 수 컨트롤 스텝 오작동 수정 완료)
# ---------------------------------------------------------
with tab3:
    st.subheader("⚙️ 여행 조건 세부 설정")
    st.caption("AI 산정 시 반영할 세부 옵션을 설정하세요.")
    
    col_a, col_b = st.columns(2)
    with col_a:
        st.session_state.start_date = st.date_input("🛫 출발일", value=st.session_state.start_date, format="YYYY/MM/DD")
    with col_b:
        st.session_state.end_date = st.date_input("🛬 도착일", value=st.session_state.end_date, format="YYYY/MM/DD")
        
    if st.session_state.end_date <= st.session_state.start_date:
        st.session_state.end_date = st.session_state.start_date + datetime.timedelta(days=1)

    t_days = (st.session_state.end_date - st.session_state.start_date).days
    st.info(f"🗓️ 현재 선택 기간: {st.session_state.start_date.strftime('%Y/%m/%d')} ~ {st.session_state.end_date.strftime('%Y/%m/%d')} ({t_days}박 {t_days+1}일)")

    st.markdown("---")
    col_c, col_d, col_e = st.columns(3)
    
    with col_c:
        # key="travel_members"로 세션과 직접 연결하여 튀는 현상 해결
        st.number_input(
            "👥 여행 인원 (명)", 
            min_value=1, 
            max_value=20, 
            step=1,
            key="travel_members"
        )

    with col_d:
        flight_options = ["LCC (저가항공)", "FSC (일반 국적기)", "비즈니스석"]
        st.session_state.flight_class = st.selectbox("✈️ 항공권 등급", flight_options, index=flight_options.index(st.session_state.flight_class))
    with col_e:
        hotel_options = ["게스트하우스/호스텔", "3성급 (가성비 호텔)", "4~5성급 (고급 호텔/리조트)"]
        st.session_state.hotel_type = st.selectbox("🏨 숙소 등급", hotel_options, index=hotel_options.index(st.session_state.hotel_type))

    st.markdown("---")
    if st.button("🔄 전체 대화 내용 초기화"):
        st.session_state.messages = []
        for key in ['current_dest', 'custom_itinerary', 'cost_data']:
            if key in st.session_state:
                del st.session_state[key]
        st.success("대화 내역이 초기화되었습니다.")
        st.rerun()
