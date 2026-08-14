from openai import OpenAI
import streamlit as st


# =========================================================
# 1. 기본 설정
# =========================================================

st.set_page_config(
    page_title="Upstage Solar Chatbot",
    page_icon="☀️"
)

st.title("☀️ Upstage Solar Chatbot")


# =========================================================
# 2. Upstage API 설정
# =========================================================
# 아래 문자열을 실제 Upstage API Key로 바꾸세요.

UPSTAGE_API_KEY = "up_Y7OKHBUB2q7pi7C4E1ILIWItBAUOG"


client = OpenAI(
    api_key=UPSTAGE_API_KEY,
    base_url="https://api.upstage.ai/v1"
)


# =========================================================
# 3. 대화 기록 초기화
# =========================================================

if "messages" not in st.session_state:
    st.session_state.messages = []


# =========================================================
# 4. 대화 초기화 버튼
# =========================================================

if st.button("대화 초기화"):
    st.session_state.messages = []
    st.rerun()


# =========================================================
# 5. 이전 대화 출력
# =========================================================

for message in st.session_state.messages:

    with st.chat_message(message["role"]):
        st.markdown(message["content"])


# =========================================================
# 6. 사용자 입력
# =========================================================

prompt = st.chat_input("메시지를 입력하세요.")


if prompt:

    # 사용자 메시지를 대화 기록에 추가
    st.session_state.messages.append(
        {
            "role": "user",
            "content": prompt
        }
    )

    # 사용자 메시지 화면에 출력
    with st.chat_message("user"):
        st.markdown(prompt)


    # =====================================================
    # 7. Solar에게 대화 전체 전달
    # =====================================================

    with st.chat_message("assistant"):

        stream = client.chat.completions.create(
            model="solar-pro3",
            messages=st.session_state.messages,
            #reasoning_effort="low",
            stream=True
        )


        # 스트리밍 응답에서 텍스트만 추출
        def generate_response():

            for chunk in stream:

                if chunk.choices:
                    content = chunk.choices[0].delta.content

                    if content:
                        yield content


        # 화면에 실시간으로 출력
        response = st.write_stream(generate_response())


    # =====================================================
    # 8. Solar의 응답도 대화 기록에 추가
    # =====================================================

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": response
        }
    )
