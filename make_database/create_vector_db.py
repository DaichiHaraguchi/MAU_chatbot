import os
import json
import numpy as np
import faiss
import google.generativeai as genai
import time

# --- 定数 ---
# direnvで設定されることを期待
API_KEY = os.getenv('GEMINI_API_KEY')
EMBEDDING_MODEL = 'models/text-embedding-004'

# パス設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, 'data','scraped_data_student_menu')
OUTPUT_DIR = os.path.join(BASE_DIR, 'data','vector_store')
FAISS_INDEX_PATH = os.path.join(OUTPUT_DIR, 'faiss_index.bin')
METADATA_PATH = os.path.join(OUTPUT_DIR, 'metadata.json')

# デバッグモード設定: 処理するJSONファイルの最大数 (Noneで全ファイル処理)
DEBUG_MODE_MAX_FILES = None # 全ファイルを処理するように変更

# --- メイン処理 ---

def create_chunks(data):
    """構造化JSONデータからチャンクを作成する"""
    chunks = []
    current_headings = []
    
    # テキストチャンク結合用の一時バッファ
    text_buffer = []

    def flush_text_buffer():
        if text_buffer:
            chunk_text = " > ".join(current_headings) + "\n" + " ".join(text_buffer)
            chunks.append({
                'source': data['url'],
                'title': data['title'],
                'headings': list(current_headings),
                'text': chunk_text
            })
            text_buffer.clear()

    for item in data['content']:
        if item['type'] == 'heading':
            flush_text_buffer() # バッファをフラッシュ
            # 見出しレベルに応じて階層を更新
            level = item['level']
            current_headings = current_headings[:level-1]
            current_headings.append(item['text'])
            
            # 見出し自体もチャンクとして追加
            chunk_text = " > ".join(current_headings)
            chunks.append({
                'source': data['url'],
                'title': data['title'],
                'headings': list(current_headings),
                'text': chunk_text
            })

        elif item['type'] == 'paragraph':
            text_buffer.append(item['text'])
            
        elif item['type'] == 'list':
            flush_text_buffer() # バッファをフラッシュ
            list_text = "\n".join([f"- {li}" for li in item['items']])
            chunk_text = " > ".join(current_headings) + "\n" + list_text
            chunks.append({
                'source': data['url'],
                'title': data['title'],
                'headings': list(current_headings),
                'text': chunk_text
            })
        
        elif item['type'] == 'table':
            flush_text_buffer() # バッファをフラッシュ
            table_headers = item['headers']
            table_rows = item['rows']
            
            # 各テーブル行を個別のチャンクとして追加
            for row_idx, row in enumerate(table_rows):
                row_str_parts = []
                for col_idx, cell_value in enumerate(row):
                    if col_idx < len(table_headers):
                        row_str_parts.append(f"{table_headers[col_idx]}: {cell_value}")
                    else:
                        row_str_parts.append(cell_value) # ヘッダーがない場合は値のみ
                
                # チャンクのテキストを生成
                chunk_text = " > ".join(current_headings) + "\n" + \
                             f"テーブル行 {row_idx+1}: " + ", ".join(row_str_parts)
                
                chunks.append({
                    'source': data['url'],
                    'title': data['title'],
                    'headings': list(current_headings),
                    'text': chunk_text
                })

    flush_text_buffer() # 最後に残ったバッファをフラッシュ
            
    return chunks

def get_embeddings_with_retry(texts, model, max_retries=5):
    """リトライ機能付きでEmbeddingを取得する"""
    try:
        # APIのレートリミットを考慮
        time.sleep(1) 
        result = genai.embed_content(model=model, content=texts, task_type="RETRIEVAL_DOCUMENT")
        return result['embedding']
    except Exception as e:
        print(f"API Error: {e}. Retrying...")
        if max_retries > 0:
            time.sleep(5) # エラー時は長めに待つ
            return get_embeddings_with_retry(texts, model, max_retries - 1)
        else:
            print("Failed to get embeddings after multiple retries.")
            raise

def main():
    """メインの実行関数"""
    if not API_KEY:
        print("エラー: 環境変数 GEMINI_API_KEY が設定されていません。direnvの設定を確認してください。")
        return

    genai.configure(api_key=API_KEY)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_chunks = []
    json_files = [f for f in os.listdir(INPUT_DIR) if f.endswith('.json')]

    # デバッグモードが有効な場合、ファイル数を制限
    if DEBUG_MODE_MAX_FILES is not None:
        json_files = json_files[:DEBUG_MODE_MAX_FILES]
        print(f"デバッグモード: {DEBUG_MODE_MAX_FILES}個のJSONファイルのみを処理します。")

    print(f"{len(json_files)}個のJSONファイルを処理します...")
    for file_name in json_files:
        file_path = os.path.join(INPUT_DIR, file_name)
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            all_chunks.extend(create_chunks(data))
    
    print(f"合計 {len(all_chunks)} 個のチャンクが作成されました。")

    # Embeddingの取得
    print("チャンクのEmbeddingを取得中... (APIコールのため時間がかかります)")
    embeddings = []
    metadata = []
    
    for i, chunk in enumerate(all_chunks):
        # テキストが空でないことを確認
        if not chunk['text'].strip():
            continue

        print(f"  Processing chunk {i+1}/{len(all_chunks)}...")
        embedding = get_embeddings_with_retry([chunk['text']], EMBEDDING_MODEL)
        embeddings.append(embedding[0]) 
        metadata.append(chunk)

    if not embeddings:
        print("有効なEmbeddingが一つも生成されませんでした。処理を中断します。")
        return

    # FAISSインデックスの作成
    print("FAISSインデックスを作成中...")
    vector_dimension = len(embeddings[0])
    print(f"[DEBUG] Creating FAISS index with dimension: {vector_dimension}")
    index = faiss.IndexFlatL2(vector_dimension)
    index.add(np.array(embeddings).astype('float32').reshape(-1, vector_dimension))

    # ファイルへの保存
    print(f"FAISSインデックスを {FAISS_INDEX_PATH} に保存中...")
    faiss.write_index(index, FAISS_INDEX_PATH)

    print(f"メタデータを {METADATA_PATH} に保存中...")
    with open(METADATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print("\nデータベースの作成が完了しました。")
    print(f"- ベクトル数: {index.ntotal}")
    print(f"- 保存先: {OUTPUT_DIR}")

if __name__ == '__main__':
    main()
