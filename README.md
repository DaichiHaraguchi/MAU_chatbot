# ムサビ通信チャットbot
このリポジトリは、ムサビ通信のシラバス検索及びお問い合わせチャットbotの実装になります

## 環境構築
脳死でコマンドをターミナル上で打っていただけると良いかと思います。
なお、dockerがインストールされていない場合は頑張ってインストールしてください。
### 1. Docker イメージのビルド
```bash
docker build -t ubuntu-python-uv .
```
### 2. コンテナを起動（インタラクティブシェル付き）
```bash
docker run -it -p 8501:8501 ubuntu-python-uv
```
### 3. pythonパッケージの同期
```bash
uv sync
```
### 4. GEMINI API KEYの設定
```bash
export GEMINI_API_KEY="YOUR API KEY"
```
```YOUR API KEY```にはご自身のGEMINI API KEYを入れてください。
無料で使えますので、ご自身で調べてください。

## データの準備
### シラバスデータのスクレイピング 
```data/```の中に以下3つが含まれていれば実行の必要なし。
- ```all_syllabus_with_overview.csv```
- ```scraped_data_student_menu/*.json```
- ```vector_store/*```

上のファイルを順に生成させるコマンドは以下の通り。
```bash
uv run python make_database/syllabus_scraper.py --base-url https://ccap02.musabi.ac.jp/
uv run python make_database/web_scraper.py --base-url https://cc.musabi.ac.jp/campus-2nd/
uv run make_database/create_vector_db.py
```
なお、```--base-url```で今回指定しているのは2025年度のページなので、それ以降の年度のデータで作りたければここを適宜変えていただけると良いかと思われる。

## アプリの実行
もしサーバー上で動かすなら```port 8501```を開放しておく必要あり
```bash
uv run streamlit run home.py
```

## 注意
基本的にGeminiが書いたコードなので、もしかしたら冗長なアルゴリズムになっているかも。