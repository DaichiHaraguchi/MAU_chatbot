# AI搭載 武蔵野美術大学シラバス検索エンジン

## 概要

このプロジェクトは、自然言語による質問を通じて武蔵野美術大学のシラバスを検索するためのAI搭載検索エンジンです。

ユーザーが「〇〇に関する授業はありますか？」といった自然な文章で質問すると、AIが質問の意図を解釈して適切なキーワードを生成し、シラバスを検索します。最終的に、検索結果の中から質問に最も合致する授業をAIが要約して提案します。

## 主な機能

-   **自然言語による検索**: 「UIデザインについて学べる授業」のような曖昧な表現でも検索が可能です。
-   **AIによるキーワード生成**: 入力された質問から、検索に最適なキーワードをAIが自動で生成します。
-   **AIによる結果要約**: 検索結果のHTMLをAIが解析し、ユーザーの質問に沿った授業の概要、担当教員名、推奨理由を分かりやすく提示します。
-   **対話的なインターフェース**: コマンドライン上で簡単に対話しながら検索を進めることができます。

## 必要なもの

-   Python 3.9 以上
-   Google Gemini APIキー

## セットアップ

1.  **リポジトリのクローンまたはダウンロード**

2.  **仮想環境の作成と有効化**
    ```bash
    python -m venv venv
    source venv/bin/activate
    ```

3.  **必要なライブラリのインストール**
    ```bash
    pip install google-generativeai requests beautifulsoup4 streamlit
    ```

4.  **APIキーの設定**
    `GEMINI_API_KEY`という名前で環境変数を設定します。`.envrc`ファイルなどを使用すると便利です。
    ```bash
    export GEMINI_API_KEY="YOUR_API_KEY"
    ```

## Streamlit Webアプリケーションの実行方法

セットアップ完了後、以下のコマンドでWebアプリケーションを起動します。

```bash
streamlit run streamlit_app.py
```

特定のポート（例: 8501）で起動したい場合は、以下のように `--server.port` オプションを使用します。

```bash
streamlit run streamlit_app.py --server.port 8501
```

初回起動時にメールアドレスの入力を求められる場合がありますが、`--server.headless true` オプションを付けて起動することで回避できます。

```bash
streamlit run streamlit_app.py --server.headless true --server.port 8501
```

## 各スクリプトの役割

-   `streamlit_app.py`: Streamlitを使用したWebアプリケーションのメインスクリプト。ユーザーからの質問受付、AIによるキーワード生成、シラバス検索、結果の要約まで、一連の処理を統括します。
