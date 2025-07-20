import streamlit as st
import os
import google.generativeai as genai
import pandas as pd
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage

# --- Constants ---
# CSV_FILE_PATH = os.path.join(os.path.dirname(__file__), "all_syllabus_with_overview.csv") # ここを修正
CSV_FILE_PATH = os.path.join(os.path.dirname(__file__), "..","data", "all_syllabus_with_overview.csv")
GENERATIVE_MODEL = 'gemini-2.5-flash'

# プロンプトファイルのパス
# SYSTEM_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "system_prompt.txt")
SYSTEM_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "syllabus_search", "prompts", "system_prompt.txt")

# --- Utility Functions ---
def load_prompt_from_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        st.error(f"プロンプトファイルが見つかりません: {filepath}")
        st.stop()
    except Exception as e:
        st.error(f"プロンプトファイルの読み込み中にエラーが発生しました: {e}")
        st.stop()

def get_api_key():
    """環境変数またはStreamlit secretsからAPIキーを取得する"""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        try:
            api_key = st.secrets["GEMINI_API_KEY"]
        except (FileNotFoundError, KeyError):
            st.error("GEMINI_API_KEYが設定されていません。環境変数またはStreamlitのsecretsに設定してください。")
            st.stop() # APIキーがない場合はアプリを停止
    return api_key

@st.cache_data
def load_all_syllabus_data(csv_path):
    """CSVファイルから全てのシラバスデータを読み込む"""
    try:
        df = pd.read_csv(csv_path)
        required_cols = ['subject_name', 'overview', 'detail_url']
        if not all(col in df.columns for col in required_cols):
            st.error(f"CSVファイルに必要なカラム ({', '.join(required_cols)}) が見つかりません。")
            st.stop()
        df = df.fillna('')
        return df
    except FileNotFoundError:
        st.error(f"エラー: シラバスCSVファイルが見つかりません: {csv_path}")
        st.stop()
    except Exception as e:
        st.error(f"エラー: CSVファイルの読み込み中に問題が発生しました: {e}")
        st.stop()

def format_syllabuses_for_llm(df):
    """DataFrameのシラバスデータをLLMに渡せる形式に整形する"""
    return "---\n".join(
        f"科目名: {row['subject_name']}\n概要: {row['overview']}\n科目URL: {row['detail_url']}"
        for index, row in df.iterrows()
    )

# --- LangChain Setup ---
def create_langchain_chain(api_key, all_syllabuses_text):
    """LangChainのチェーンを作成する"""
    # LLM
    llm = ChatGoogleGenerativeAI(model=GENERATIVE_MODEL, google_api_key=api_key, stream=True)

    # Prompt
    system_prompt_template = load_prompt_from_file(SYSTEM_PROMPT_PATH)
    system_prompt = system_prompt_template.format(all_syllabuses_text=all_syllabuses_text)

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{question}"),
    ])

    # Chain
    chain = prompt | llm
    return chain

# --- Streamlit App ---
st.set_page_config(page_title="シラバスAIチャット", page_icon="🎓")
st.title("🎓 シラバス検索")
st.write("ムサビ通信のシラバスをチャット形式で検索できます。")
st.warning("注意:入力トークン制限に達し、エラーが出る可能性があります。")

# ページがロードされたときにチャット履歴をリセット
if "last_page_loaded" not in st.session_state or st.session_state.last_page_loaded != "syllabus_chat_page":
    st.session_state.chat_history = []
    st.session_state.last_page_loaded = "syllabus_chat_page"

# --- Initialization ---
try:
    api_key = get_api_key()
    genai.configure(api_key=api_key)
except Exception as e:
    st.error(f"APIキーの設定中にエラーが発生しました: {e}")
    st.stop()

all_syllabus_df = load_all_syllabus_data(CSV_FILE_PATH)
all_syllabuses_formatted_text = format_syllabuses_for_llm(all_syllabus_df)

# LangChainのチェーンをセッション状態で管理
if "chain" not in st.session_state:
    st.session_state.chain = create_langchain_chain(api_key, all_syllabuses_formatted_text)

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# --- Chat Interface ---
# Display chat messages from history
for message in st.session_state.chat_history:
    if isinstance(message, HumanMessage):
        with st.chat_message("user"):
            st.markdown(message.content)
    elif isinstance(message, AIMessage):
        with st.chat_message("assistant"):
            st.markdown(message.content)

# Accept user input
if user_question := st.chat_input("どのような授業を探しますか？"):
    # Add user message to history and display
    st.session_state.chat_history.append(HumanMessage(content=user_question))
    with st.chat_message("user"):
        st.markdown(user_question)

    # Generate and display AI response
    with st.chat_message("assistant"):
        with st.spinner("AIが考えています..."):
            try:
                response_stream = st.session_state.chain.stream({
                    "chat_history": st.session_state.chat_history,
                    "question": user_question
                })
                full_response = st.write_stream(response_stream)
                st.session_state.chat_history.append(AIMessage(content=full_response))
            except Exception as e:
                st.error(f"回答生成中にエラーが発生しました: {e}")
                # Remove the last user message if AI fails
                if st.session_state.chat_history: # 履歴が空でないことを確認
                    st.session_state.chat_history.pop()
