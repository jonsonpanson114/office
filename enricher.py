"""
Gemini 3.1 Flash Lite を使用した画像説明文・タグ生成モジュール。
Antigravity Standard Version 3.1 準拠。
"""

import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image

load_dotenv()

# 最新モデル定義
GEN_MODEL_ID = "gemini-3.1-flash-lite-preview"
EMBEDDING_MODEL = "gemini-embedding-2-preview"
EMBEDDING_DIMENSION = 768 # デフォルト

DATA_DIR = Path(__file__).parent / "data"
RAW_DATA_PATH = DATA_DIR / "raw_data.json"
ENRICHED_DATA_PATH = DATA_DIR / "enriched_data.json"

PROMPT_TEMPLATE = """この画像は『{project_name}』の施工事例で、使用製品は『{products}』、場所は『{location}』です。
この空間を建築・インテリアデザインのプロの視点で分析し、以下の項目を正確な JSON 形式で出力してください。

1. "description": 空間の『雰囲気』『デザインの特徴』『利用シーン』を感性豊かに記述した詳細な文章（日本語）。
2. "style": 代表的なインテリアスタイル（例：モダン、インダストリアル、ナチュラル、和モダン、ミニマル、北欧風、クラシック等）を1つ選択。
3. "colors": 空間を構成する主要なカラーパレット（3〜5色程度の色の名前）。
4. "advice": この空間の魅力を引き出すための、あるいは同様の空間を作るためのプロのデザインアドバイス（100文字程度）。

事実に基づき、かつ空間の美しさが伝わるように記述してください。JSON 以外のテキストは含めないでください。"""


def get_client():
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    # フォールバック: .env を直接読み込む
    if not api_key and os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                if "=" in line:
                    key, val = line.split("=", 1)
                    if "GEMINI_API_KEY" in key or "GOOGLE_API_KEY" in key:
                        api_key = val.strip().strip('"').strip("'")
                        break
    
    if not api_key:
        raise ValueError(
            "GOOGLE_API_KEY または GEMINI_API_KEY 環境変数を設定してください。"
        )
    return genai.Client(api_key=api_key)


def generate_description(
    client: genai.Client,
    image_path: str,
    project_name: str,
    products: list[str],
    location: str,
) -> dict:
    prompt = PROMPT_TEMPLATE.format(
        project_name=project_name,
        products="、".join(products) if products else "不明",
        location=location,
    )
    try:
        img = Image.open(image_path)
        # google-genai SDK (v1) call
        response = client.models.generate_content(
            model=GEN_MODEL_ID,
            contents=[prompt, img]
        )
        
        text = response.text
        # JSON 抽出ロジック (Markdown ブロックを考慮)
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        
        data = json.loads(text.strip())
        return data
    except Exception as e:
        print(f"[Enricher] 生成・解析エラー ({image_path}): {e}")
        return {}


def run_enricher() -> list[dict]:
    client = get_client()

    # 既存データの読み込み (再開用)
    enriched_map = {}
    if ENRICHED_DATA_PATH.exists():
        print("[Enricher] 既存の enriched_data.json を読み込みます。")
        try:
            with open(ENRICHED_DATA_PATH, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
                for item in existing_data:
                    enriched_map[item["case_id"]] = item
        except json.JSONDecodeError:
            print("[Enricher] JSON破損。バックアップして新規作成します。")
            ENRICHED_DATA_PATH.rename(ENRICHED_DATA_PATH.with_suffix(".json.bak"))

    if not RAW_DATA_PATH.exists():
        raise FileNotFoundError(
            f"{RAW_DATA_PATH} が見つかりません。先に scraper.py を実行してください。"
        )

    with open(RAW_DATA_PATH, "r", encoding="utf-8") as f:
        raw_cases = json.load(f)

    print(f"[Enricher] 合計 {len(raw_cases)} 件のデータを処理対象とします。")

    enriched_list = []
    
    for i, case in enumerate(raw_cases):
        case_id = case["case_id"]
        
        # 既に処理済みで、画像数も一致しているか確認
        if case_id in enriched_map:
            existing_case = enriched_map[case_id]
            # 画像パスのリストが存在し、処理済みの説明文数と一致すればスキップ
            raw_img_count = len(case.get("local_image_paths", []))
            # descriptionが空でないものだけをカウント
            enriched_descs = [d for d in existing_case.get("descriptions", []) if d.get("description")]
            enriched_desc_count = len(enriched_descs)
            
            if raw_img_count == enriched_desc_count:
                enriched_list.append(existing_case)
                continue
        
        # ここに来たら処理が必要
        print(f"[Enricher] 処理中 ({i+1}/{len(raw_cases)}): {case['project_name']}")
        
        case_enriched = {**case, "descriptions": []}
        project_name = case.get("project_name", "不明")
        products = case.get("products", [])
        location = case.get("location", "不明")
        image_paths = case.get("local_image_paths", [])

        # 既存のケースデータがあれば取得
        existing_case_data = enriched_map.get(case_id, {})
        existing_items = existing_case_data.get("descriptions", [])

        print(f"[Enricher] 処理中 ({i+1}/{len(raw_cases)}): {project_name}")
        
        # 各画像の解析
        image_results = []
        for img_path_str in image_paths:
            img_name = Path(img_path_str).name
            
            # 既存チェック (description だけでなく style もあるか確認)
            existing_desc = next((d for d in existing_items if d.get("image_name") == img_name), None)
            if existing_desc and existing_desc.get("style"):
                # 既にスタイル情報があればスキップ
                image_results.append(existing_desc)
                continue

            print(f"  - 解析中 (Design Insight): {img_name}")
            result_data = generate_description(
                client, img_path_str, project_name, products, location
            )
            
            if result_data:
                res_obj = {
                    "image_name": img_name,
                    "image_path": img_path_str,
                    "description": result_data.get("description", ""),
                    "style": result_data.get("style", ""),
                    "colors": result_data.get("colors", []),
                    "advice": result_data.get("advice", ""),
                }
                image_results.append(res_obj)
                time.sleep(1) # API レート制限考慮
            else:
                # エラー時は既存があればそれを維持
                if existing_desc:
                    image_results.append(existing_desc)

        case["descriptions"] = image_results
        
        enriched_list.append(case) # caseオブジェクト自体を更新して追加
        
        # 1件ごとに保存
        with open(ENRICHED_DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(enriched_list, f, ensure_ascii=False, indent=2)

    print(f"[Enricher] 全完了: {len(enriched_list)} 件を {ENRICHED_DATA_PATH} に保存しました。")
    return enriched_list


if __name__ == "__main__":
    run_enricher()
