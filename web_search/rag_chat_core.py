import os
import json
import numpy as np
import faiss
import google.generativeai as genai
import time
import threading
import traceback

# --- 定数 ---
API_KEY = os.getenv('GEMINI_API_KEY')
EMBEDDING_MODEL = 'models/text-embedding-004'
GENERATION_MODEL = 'gemini-2.5-flash'

# パス設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VECTOR_STORE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__),'..','data', 'vector_store'))
FAISS_INDEX_PATH = os.path.join(VECTOR_STORE_DIR, 'faiss_index.bin')
METADATA_PATH = os.path.join(VECTOR_STORE_DIR, 'metadata.json')

# FAISS検索のタイムアウト (秒)
FAISS_SEARCH_TIMEOUT = 30

class RAGChatSystem:
    def __init__(self):
        print("[DEBUG] RAGChatSystem initializing...")
        if not API_KEY:
            raise ValueError("GEMINI_API_KEY environment variable not set.")
        genai.configure(api_key=API_KEY)
        print("[DEBUG] GEMINI_API_KEY is set and configured.")
        self.index = None
        self.metadata = None
        self._load_vector_store()
        self.previous_source_documents = [] # 過去の参照ドキュメントを記憶するためのリスト
        print("[DEBUG] RAGChatSystem initialized successfully.")

    def _load_vector_store(self):
        """FAISSインデックスとメタデータをロードする"""
        print("[DEBUG] Loading vector store...")
        if not os.path.exists(FAISS_INDEX_PATH) or not os.path.exists(METADATA_PATH):
            raise FileNotFoundError(
                f"Vector store files not found. Please run create_vector_db.py first.\n"
                f"Expected: {FAISS_INDEX_PATH} and {METADATA_PATH}"
            )
        self.index = faiss.read_index(FAISS_INDEX_PATH)
        with open(METADATA_PATH, 'r', encoding='utf-8') as f:
            self.metadata = json.load(f)
        print(f"Loaded FAISS index with {self.index.ntotal} vectors.")
        print(f"Loaded metadata for {len(self.metadata)} chunks.")
        print(f"[DEBUG] Loaded FAISS index dimension: {self.index.d}")

        # --- FAISS機能テスト ---
        try:
            test_query_vec = np.random.rand(1, self.index.d).astype('float32')
            test_distances, test_indices = self.index.search(test_query_vec, 1)
            print(f"[DEBUG] FAISS self-test successful. Test distance: {test_distances[0][0]:.4f}, Test index: {test_indices[0][0]}")
        except Exception as e:
            print(f"[DEBUG] ERROR: FAISS self-test failed during load: {e}")
            raise
        # --- FAISS機能テスト終わり ---

    def _get_embedding(self, text, task_type="RETRIEVAL_QUERY", chat_history=None, max_retries=5):
        """Gemini APIでEmbeddingを取得する (リトライ機能付き、チャット履歴を考慮)"""
        content_to_embed = text
        if chat_history:
            # Streamlitのst.session_state.messagesの形式を想定
            history_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in chat_history])
            content_to_embed = f"{history_str}\nユーザーの質問: {text}"

        print(f"[DEBUG] Getting embedding for content (first 50 chars): {content_to_embed[:50]}...")
        try:
            time.sleep(0.1)
            result = genai.embed_content(model=EMBEDDING_MODEL, content=content_to_embed, task_type=task_type)
            print("[DEBUG] Embedding obtained successfully.")
            return result['embedding']
        except Exception as e:
            print(f"[DEBUG] Embedding API Error: {e}. Retrying...")
            if max_retries > 0:
                time.sleep(5)
                return self._get_embedding(text, task_type, chat_history, max_retries - 1)
            else:
                print("[DEBUG] Failed to get embedding after multiple retries.")
                raise

    def _faiss_search_thread(self, query_embedding_np, k, result_container):
        """FAISS検索を別スレッドで実行する"""
        try:
            distances, indices = self.index.search(query_embedding_np, k)
            result_container['result'] = (distances, indices)
        except Exception as e:
            error_message = f"FAISS search thread exception: {e}\n{traceback.format_exc()}"
            print(f"[DEBUG] {error_message}")
            result_container['error'] = error_message

    def _convert_json_to_markdown(self, json_data):
        """構造化JSONデータをMarkdown形式に変換する"""
        markdown_parts = []
        
        if 'title' in json_data and json_data['title']:
            markdown_parts.append(f"# {json_data['title']}")
        if 'url' in json_data and json_data['url']:
            markdown_parts.append(f"URL: {json_data['url']}\n")

        for item in json_data['content']:
            if item['type'] == 'heading':
                level = min(item['level'], 6)
                markdown_parts.append(f"{'#' * level} {item['text']}")
            elif item['type'] == 'paragraph':
                markdown_parts.append(item['text'])
            elif item['type'] == 'list':
                for li_item in item['items']:
                    markdown_parts.append(f"- {li_item}")
            elif item['type'] == 'table':
                headers = item.get('headers', [])
                rows = item.get('rows', [])

                if headers:
                    markdown_parts.append("| " + " | ".join(headers) + " |")
                    markdown_parts.append("|" + "---"*len(headers) + "|")
                
                for row in rows:
                    markdown_parts.append("| " + " | ".join(row) + " |")
            
            markdown_parts.append("")
            
        return "\n".join(markdown_parts).strip()

    # --- NEW: キーワードマップとキーワードマッチング関数 ---
    KEYWORD_MAP = {
        "https://cc.musabi.ac.jp/campus-2nd/faq": ["よくある質問", "質問", "疑問"],
        "https://cc.musabi.ac.jp/campus-2nd/qualification-course": ["教職課程", "学芸員課程", "教員免許", "学芸員資格", "資格取得", "課程", "履修費", "費用"],
        "https://cc.musabi.ac.jp/campus-2nd/schooling": ["スクーリング", "面接授業", "受講", "授業", "費用", "受講料"],
        "https://cc.musabi.ac.jp/campus-2nd/registration": ["履修登録", "登録", "履修", "費用", "履修費"],
        "https://cc.musabi.ac.jp/campus-2nd/school": ["学費", "授業料", "入学金", "年間費用", "学校費用", "納入", "支払い"],
        "https://cc.musabi.ac.jp/campus-2nd/gpa": ["成績", "GPA", "評価", "単位"],
    }

    def _get_keyword_matched_files(self, query_tokens):
        """
        ユーザーのクエリキーワードに基づいて、関連性の高いJSONファイルを特定する。
        戻り値は {source_url: match_count} の辞書。
        """
        print(f"[debug]:tokens --- {query_tokens}")
        matched_files_scores = {}
        for source_url, keywords in self.KEYWORD_MAP.items():
            count = 0
            for q_token in query_tokens:
                for file_kw in keywords:
                    if q_token in file_kw or file_kw in q_token:
                        count += 1
            if count > 0:
                matched_files_scores[source_url] = count
        return matched_files_scores
    # --- END NEW ---

    def _extract_keywords_with_llm(self, query):
        """LLMを使ってユーザーの質問からキーワードを抽出する"""
        keyword_extraction_prompt_path = os.path.join(BASE_DIR, 'prompts', 'keyword_extraction_prompt.txt')
        with open(keyword_extraction_prompt_path, 'r', encoding='utf-8') as f:
            keyword_extraction_prompt_template = f.read()
        keyword_extraction_prompt = keyword_extraction_prompt_template.format(query=query)
        try:
            model = genai.GenerativeModel(GENERATION_MODEL)
            response = model.generate_content(keyword_extraction_prompt)
            keywords_str = response.text.strip()
            # カンマで分割し、各キーワードの空白を削除
            keywords = [kw.strip() for kw in keywords_str.split(',') if kw.strip()]
            print(f"[DEBUG] Extracted keywords: {keywords}")
            return keywords
        except Exception as e:
            print(f"[DEBUG] Error extracting keywords with LLM: {e}. Falling back to simple split.")
            return query.lower().split() # エラー時はフォールバック

    def process_chat_query(self, query, chat_history=None, k=5):
        """チャットクエリを処理し、回答と情報源を返す"""
        print(f"--- Starting new chat flow for query: {query} ---")

        # 1. クエリ拡張を削除し、元のクエリを直接使用
        processed_query = query

        # 2. ユーザーのプロンプトをキーワードに分解 (LLMを使用)
        query_tokens = self._extract_keywords_with_llm(processed_query)
        print(f"[DEBUG]:query tokens ------- {query_tokens}")

        # 3. キーワードが含まれるJSONの一致度でファイルを選定
        keyword_matched_scores = self._get_keyword_matched_files(query_tokens)
        print(f"[VOTING] Keyword matched scores: {keyword_matched_scores}")

        files_to_process = []

        # 優先順位1: キーワードマッチしたファイルが存在する場合
        if keyword_matched_scores:
            sorted_keyword_files = sorted(keyword_matched_scores.items(), key=lambda item: item[1], reverse=True)
            files_to_process.append(sorted_keyword_files[0][0]) # 最もスコアの高いファイルは必ず含める

            if len(sorted_keyword_files) >= 2:
                top_score = sorted_keyword_files[0][1]
                second_file_url, second_file_score = sorted_keyword_files[1]
                if second_file_score >= (top_score * 0.65): # 閾値は0.65
                    files_to_process.append(second_file_url)
                else:
                    print(f"[VOTING] Second keyword-matched file ({second_file_url}) score ({second_file_score}) is too low compared to top ({top_score}). Only returning top keyword-matched file.")
            print(f"[VOTING] Files selected via keyword match: {files_to_process}")

        else: # キーワードマッチしたファイルがない場合、FAISS検索にフォールバック
            # 4. FAISS検索 (当たりをつける)
            print(f"[VOTING] Step 1: Searching for top {k} chunks with query: {processed_query}...")
            faiss_voted_scores = {}
            try:
                # chat_historyを_get_embeddingに渡す
                query_embedding = self._get_embedding(processed_query, task_type="RETRIEVAL_QUERY", chat_history=chat_history)
                query_embedding_np = np.array([query_embedding]).astype('float32')
                
                distances, indices = self.index.search(query_embedding_np, k)
                
                if indices.size > 0:
                    initial_retrieved_chunks = []
                    for i, idx in enumerate(indices[0]):
                        if idx < len(self.metadata):
                            chunk = self.metadata[idx]
                            chunk['distance'] = distances[0][i]
                            initial_retrieved_chunks.append(chunk)

                    filtered_chunks_for_voting = initial_retrieved_chunks
                    print(f"[VOTING] {len(filtered_chunks_for_voting)} chunks will be used for voting.")

                    print("[VOTING] Step 2: Voting for files based on FAISS chunks...")
                    for chunk in filtered_chunks_for_voting:
                        source_file = chunk['source']
                        faiss_voted_scores[source_file] = faiss_voted_scores.get(source_file, 0) + 1
                    
                    print(f"[VOTING] FAISS voted scores: {faiss_voted_scores}")
                else:
                    print("[VOTING] No chunks found via FAISS.")

            except Exception as e:
                print(f"[VOTING] Error during FAISS chunk search: {e}")

            # FAISS検索結果からファイルを選定
            if faiss_voted_scores:
                sorted_faiss_files = sorted(faiss_voted_scores.items(), key=lambda item: item[1], reverse=True)
                files_to_process.append(sorted_faiss_files[0][0]) # 最もスコアの高いファイルは必ず含める

                if len(sorted_faiss_files) >= 2:
                    top_score = sorted_faiss_files[0][1]
                    second_file_url, second_file_score = sorted_faiss_files[1]
                    if second_file_score >= (top_score * 0.65): # 閾値は0.65
                        files_to_process.append(second_file_url)
                    else:
                        print(f"[VOTING] Second FAISS-retrieved file ({second_file_url}) score ({second_file_score}) is too low compared to top ({top_score}). Only returning top FAISS-retrieved file.")
            print(f"[VOTING] Files selected via FAISS fallback: {files_to_process}")

        # 最終的に処理するファイルリスト
        # 過去の参照ドキュメントと現在の検索結果を結合
        all_candidate_files = files_to_process + self.previous_source_documents
        # 重複を排除し、順序を保持
        files_to_process = list(dict.fromkeys(all_candidate_files))
        files_to_process = files_to_process[:3] # 最大3つに制限 (過去のコンテキストも考慮するため少し増やす)
        print(f"[VOTING] Final files to process (after heuristic): {files_to_process}")

        if not files_to_process:
            print("[VOTING] No relevant files found after all search attempts.")
            return "関連する情報を見つけることができませんでした。", []

        combined_context_parts = []
        source_documents_used = []

        # 6. 選択されたファイルのコンテンツを読み込み、結合する
        for i, file_source in enumerate(files_to_process):
            print(f"[VOTING] Step 3: Reading content of file: {file_source}...")
            try:
                file_name = file_source.split('/')[-1] + ".json"
                file_path = os.path.abspath(os.path.join(BASE_DIR, '..', 'data', 'scraped_data_student_menu', file_name))
                
                with open(file_path, 'r', encoding='utf-8') as f:
                    document_data = json.load(f)
                
                markdown_content = self._convert_json_to_markdown(document_data)
                combined_context_parts.append(f"--- Document {i+1} (Source: {file_source})\n{markdown_content}\n")
                source_documents_used.append(file_source)
                print(f"[VOTING] Successfully loaded and converted {file_name} to Markdown.")

            except Exception as e:
                print(f"[VOTING] Error reading file {file_path}: {e}. Skipping this file.")
                continue
        
        if not combined_context_parts:
            print("[VOTING] No valid files were processed for context.")
            return "関連する情報を見つけることができませんでした。", []

        full_context = "\n\n".join(combined_context_parts)

        # --- デバッグ用: 生成されたMarkdownをファイルに保存 ---
        debug_output_dir = os.path.abspath(os.path.join(BASE_DIR, '..', 'data', 'debug_output'))
        os.makedirs(debug_output_dir, exist_ok=True)
        debug_file_path = os.path.join(debug_output_dir, 'last_context.md')
        with open(debug_file_path, 'w', encoding='utf-8') as f:
                f.write(full_context)
        print(f"[VOTING] Debug: Combined Markdown context saved to {debug_file_path}")
        # ---------------------------------------------------

        # 7. 結合されたファイル全体で回答生成
        print("[VOTING] Step 4: Generating answer with the combined full file context...")
        
        # チャット履歴を考慮したプロンプトは不要になるため削除
        # チャット履歴を考慮したプロンプトは不要になるため削除
        # chat_history_str = ""
        # if chat_history:
        #     chat_history_str = "\n".join([f"{'ユーザー' if i % 2 == 0 else 'アシスタント'}: {msg}" for i, msg in enumerate(chat_history)])
        #     chat_history_str = f"これまでの会話履歴:\n{chat_history_str}\n"

        prompt_file_path = os.path.join(BASE_DIR, 'prompts', 'rag_chat_prompt.txt')
        with open(prompt_file_path, 'r', encoding='utf-8') as f:
            prompt_template = f.read()
        prompt = prompt_template.format(full_context=full_context, query=query)
        
        print(f"[VOTING] Prompt for generation (first 300 chars): {prompt[:300]}...")
        try:
            model = genai.GenerativeModel(GENERATION_MODEL)
            response = model.generate_content(prompt)
            final_answer = response.text
            print("[VOTING] Successfully generated the final_answer.")
            self.previous_source_documents = list(set(source_documents_used)) # 今回使用した情報源を記憶
            return final_answer, list(set(source_documents_used))
        except Exception as e:
            print(f"[VOTING] Error during final answer generation: {e}")
            return f"最終的な回答の生成中にエラーが発生しました: {e}", list(set(source_documents_used))

if __name__ == '__main__':
    # 新しいチャットベースのRAGシステムをテストする
    try:
        rag_chat_system = RAGChatSystem()
        
        print(f"\n--- Testing new chat flow ---")
        
        # 最初の質問
        query1 = "学費はいくらですか？"
        chat_history1 = []
        print(f"User Query 1: {query1}")
        answer1, sources1 = rag_chat_system.process_chat_query(query1, chat_history1)
        print("\n--- Answer 1 ---")
        print(f"Answer: {answer1}")
        print(f"Source Documents: {sources1}")
        print("---------------------\n")

        # 2番目の質問 (履歴を考慮)
        query2 = "スクーリングの費用は？"
        # Streamlitのst.session_state.messagesの形式を模倣
        chat_history2 = [{"role": "user", "content": query1}, {"role": "assistant", "content": answer1}] 
        print(f"User Query 2: {query2}")
        answer2, sources2 = rag_chat_system.process_chat_query(query2, chat_history2)
        print("\n--- Answer 2 ---")
        print(f"Answer: {answer2}")
        print(f"Source Documents: {sources2}")
        print("---------------------\n")

    except ValueError as e:
        print(f"設定エラー: {e}")
    except FileNotFoundError as e:
        print(f"ファイルエラー: {e}")
    except Exception as e:
        print(f"予期せぬエラー: {e}")