import streamlit as st
from rag_chat_core import RAGChatSystem # 新しいクラスをインポート
import os

# --- 環境変数チェック ---
if os.getenv('GEMINI_API_KEY') is None:
    st.error("GEMINI_API_KEY 環境変数が設定されていません。direnvの設定を確認してください。")
    st.stop()

# --- RAGシステム初期化 ---
@st.cache_resource
def load_rag_chat_system():
    try:
        return RAGChatSystem()
    except Exception as e:
        st.error(f"RAGチャットシステムの初期化に失敗しました: {e}")
        st.stop()

rag_chat_system = load_rag_chat_system()

# --- Streamlit UI ---
st.title("2025年度 武蔵野美術大学 通信教育課程 お問い合わせチャットシbot")
st.write("在学生（学2課程）向けの情報に特化したチャットbotです。質問を入力してください。")

# チャット履歴の初期化
if "messages" not in st.session_state:
    st.session_state.messages = []

# 過去のメッセージを表示
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        # 情報源があれば表示
        if "sources" in message and message["sources"]:
            with st.expander("参照情報"):
                for i, source_url in enumerate(message["sources"]):
                    st.write(f"**参照 {i+1}:** {source_url}")

# ユーザーからの入力
if prompt := st.chat_input("質問を入力してください..."):
    # ユーザーメッセージを履歴に追加
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("回答を生成中..."):
            try:
                # st.session_state.messagesからチャット履歴を構築
                # rag_chat_coreの_get_embeddingが期待する形式に変換
                chat_history_for_rag = []
                for msg in st.session_state.messages:
                    chat_history_for_rag.append({"role": msg["role"], "content": msg["content"]})

                final_answer, source_documents_used = rag_chat_system.process_chat_query(prompt, chat_history=chat_history_for_rag)
                st.markdown(final_answer)

            except Exception as e:
                st.error(f"エラーが発生しました: {e}")
                final_answer = f"エラーが発生しました: {e}"
                source_documents_used = [] # エラー時は情報源なし
                # st.stop() # エラー時にアプリが停止しないようにコメントアウト
        # アシスタントの回答を履歴に追加 (情報源も一緒に保存)
        st.session_state.messages.append({"role": "assistant", "content": final_answer, "sources": source_documents_used})