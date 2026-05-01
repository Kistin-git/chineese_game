import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st
import streamlit.components.v1 as components


st.set_page_config(page_title="Chinese Visual Matching Builder", page_icon="汉", layout="wide")
BASE_DIR = Path(__file__).resolve().parent

PUNCT_ONLY_RE = re.compile(r"^[\s，。！？；：、“”‘’（）()《》〈〉【】…,.!?:;\"'`·—-]+$")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])")


def special_format_template() -> str:
    return textwrap_dedent(
        """
        TITLE: Пример набора

        PARAGRAPH
        HANZI: 教授，您好！本人名叫伊万，想请教您一些事。
        PINYIN: Jiàoshòu, nín hǎo! Běnrén míng jiào Yīwàn, xiǎng qǐngjiào nín yìxiē shì.
        RUSSIAN: Профессор, здравствуйте! Меня зовут Иван, я хотел бы задать вам несколько вопросов.

        SENTENCE
        HANZI: 教授，您好！
        PINYIN: Jiàoshòu, nín hǎo!
        RUSSIAN: Профессор, здравствуйте!
        WORDS
        - 教授 | jiàoshòu | профессор
        - 您好 | nín hǎo | здравствуйте
        END_WORDS
        END_SENTENCE

        SENTENCE
        HANZI: 本人名叫伊万，想请教您一些事。
        PINYIN: Běnrén míng jiào Yīwàn, xiǎng qǐngjiào nín yìxiē shì.
        RUSSIAN: Меня зовут Иван, я хотел бы задать вам несколько вопросов.
        WORDS
        - 本人 | běnrén | я сам; лично я
        - 名叫 | míng jiào | зваться
        - 伊万 | Yīwàn | Иван
        - 想 | xiǎng | хотеть
        - 请教 | qǐngjiào | вежливо спросить; посоветоваться
        - 您 | nín | Вы (вежливо)
        - 一些 | yìxiē | некоторые
        - 事 | shì | дела; вопросы
        END_WORDS
        END_SENTENCE

        END_PARAGRAPH
        """
    ).strip()


def special_format_presets() -> Dict[str, str]:
    preset_file = BASE_DIR / "templates" / "ivan_liu_dialog_special_format.txt"
    presets = {
        "Минимальный шаблон": special_format_template(),
    }
    if preset_file.exists():
        presets["Диалог Иван — профессор Лю"] = preset_file.read_text(encoding="utf-8")
    return presets


def llm_prompt_for_special_format() -> str:
    return textwrap_dedent(
        """
        Преобразуй китайский текст в специальный формат для игры.

        Правила:
        1. Сохрани порядок абзацев.
        2. Разбей каждый абзац на естественные предложения.
        3. Для каждого абзаца укажи:
           - HANZI
           - PINYIN
           - RUSSIAN
        4. Для каждого предложения укажи:
           - HANZI
           - PINYIN
           - RUSSIAN
        5. В блоке WORDS перечисли ВСЕ слова или осмысленные чанки предложения строго по порядку.
        6. Нельзя пропускать частицы, местоимения, служебные слова, повторяющиеся слова и дубликаты.
        7. Если слово встречается дважды, оно должно быть записано дважды.
        8. Каждая строка WORDS должна быть в виде:
           - иероглифы | pinyin с тонами | краткий перевод на русский
        9. Не добавляй markdown, JSON, пояснения или текст вне формата.

        Используй строго такой формат:

        TITLE: Название набора

        PARAGRAPH
        HANZI: ...
        PINYIN: ...
        RUSSIAN: ...

        SENTENCE
        HANZI: ...
        PINYIN: ...
        RUSSIAN: ...
        WORDS
        - ...
        - ...
        END_WORDS
        END_SENTENCE

        SENTENCE
        ...
        END_SENTENCE

        END_PARAGRAPH

        Если абзацев несколько, повторяй блок PARAGRAPH для каждого абзаца.
        """
    ).strip()


def textwrap_dedent(text: str) -> str:
    import textwrap

    return textwrap.dedent(text)


def split_paragraphs(source_text: str) -> List[str]:
    return [block.strip() for block in re.split(r"\n\s*\n", source_text) if block.strip()]


def split_sentences(paragraph_text: str) -> List[str]:
    chunks = [item.strip() for item in SENTENCE_SPLIT_RE.split(paragraph_text) if item.strip()]
    if not chunks:
        return [paragraph_text.strip()]
    return chunks


def ensure_free_dependencies() -> None:
    missing = []
    for module_name in ("jieba", "pypinyin", "deep_translator"):
        try:
            __import__(module_name)
        except ImportError:
            missing.append(module_name)
    if missing:
        raise RuntimeError(
            "Не хватает пакетов для бесплатного режима: "
            + ", ".join(missing)
            + ". Установите зависимости из requirements.txt."
        )


@st.cache_data(show_spinner=False)
def translate_text_cached(text: str) -> str:
    from deep_translator import GoogleTranslator

    translator = GoogleTranslator(source="zh-CN", target="ru")
    return translator.translate(text)


def build_sentence_pinyin(sentence: str) -> str:
    from pypinyin import Style, pinyin

    syllables = []
    for chunk in pinyin(sentence, style=Style.TONE, errors=lambda value: list(value)):
        piece = "".join(chunk).strip()
        if not piece:
            continue
        if PUNCT_ONLY_RE.match(piece):
            if syllables:
                syllables[-1] = syllables[-1] + piece
            else:
                syllables.append(piece)
        else:
            syllables.append(piece)
    return " ".join(syllables).strip()


def tokenize_sentence(sentence: str) -> List[str]:
    import jieba

    tokens = []
    for token in jieba.lcut(sentence, cut_all=False):
        chunk = token.strip()
        if not chunk:
            continue
        if PUNCT_ONLY_RE.match(chunk):
            continue
        tokens.append(chunk)
    return tokens


def build_word_entry(token: str, counter: str) -> Dict[str, str]:
    return {
        "hanzi": token,
        "pinyin": build_sentence_pinyin(token),
        "russian": translate_text_cached(token),
        "instance_id": counter,
    }


def parse_special_format(raw_text: str) -> Dict[str, Any]:
    title = "Новый китайский текст"
    paragraphs = []
    current_paragraph = None
    current_sentence = None
    in_words = False

    def append_sentence() -> None:
        nonlocal current_sentence, current_paragraph, in_words
        if current_sentence is None:
            return
        if not current_sentence.get("hanzi") or not current_sentence.get("words"):
            raise ValueError("В одном из блоков SENTENCE отсутствуют HANZI или WORDS.")
        current_paragraph["sentences"].append(current_sentence)
        current_sentence = None
        in_words = False

    def append_paragraph() -> None:
        nonlocal current_paragraph
        if current_paragraph is None:
            return
        if current_sentence is not None:
            append_sentence()
        if not current_paragraph["sentences"]:
            raise ValueError("В одном из блоков PARAGRAPH нет ни одного SENTENCE.")
        paragraphs.append(current_paragraph)
        current_paragraph = None

    for line_number, raw_line in enumerate(raw_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("TITLE:"):
            title = line.split(":", 1)[1].strip() or title
            continue

        if line == "PARAGRAPH":
            append_paragraph()
            current_paragraph = {"sentences": [], "hanzi": "", "pinyin": "", "russian": ""}
            continue

        if line == "END_PARAGRAPH":
            if current_paragraph is None:
                raise ValueError(f"Строка {line_number}: END_PARAGRAPH без открытого PARAGRAPH.")
            append_paragraph()
            continue

        if line == "SENTENCE":
            if current_paragraph is None:
                raise ValueError(f"Строка {line_number}: SENTENCE вне PARAGRAPH.")
            if current_sentence is not None:
                append_sentence()
            current_sentence = {"hanzi": "", "pinyin": "", "russian": "", "words": []}
            continue

        if line == "END_SENTENCE":
            if current_sentence is None:
                raise ValueError(f"Строка {line_number}: END_SENTENCE без открытого SENTENCE.")
            append_sentence()
            continue

        if line == "WORDS":
            if current_sentence is None:
                raise ValueError(f"Строка {line_number}: WORDS вне SENTENCE.")
            in_words = True
            continue

        if line == "END_WORDS":
            if current_sentence is None:
                raise ValueError(f"Строка {line_number}: END_WORDS вне SENTENCE.")
            in_words = False
            continue

        if in_words:
            if not line.startswith("- "):
                raise ValueError(f"Строка {line_number}: строка слова должна начинаться с '- '.")
            parts = [part.strip() for part in line[2:].split("|")]
            if len(parts) != 3:
                raise ValueError(f"Строка {line_number}: слово должно быть в формате 'hanzi | pinyin | russian'.")
            current_sentence["words"].append(
                {
                    "hanzi": parts[0],
                    "pinyin": parts[1],
                    "russian": parts[2],
                }
            )
            continue

        if ":" not in line:
            raise ValueError(f"Строка {line_number}: нераспознанная строка '{line}'.")

        key, value = [item.strip() for item in line.split(":", 1)]
        key = key.upper()

        if current_sentence is not None and key in {"HANZI", "PINYIN", "RUSSIAN"}:
            current_sentence[key.lower()] = value
            continue

        if current_paragraph is not None and current_sentence is None and key in {"HANZI", "PINYIN", "RUSSIAN"}:
            current_paragraph[key.lower()] = value
            continue

        raise ValueError(f"Строка {line_number}: ключ '{key}' находится не в том блоке.")

    if current_sentence is not None:
        append_sentence()
    if current_paragraph is not None:
        append_paragraph()

    return normalize_dataset({"title": title, "paragraphs": paragraphs})


def generate_dataset_free(source_text: str, title: str) -> Dict[str, Any]:
    ensure_free_dependencies()

    paragraphs = []
    for paragraph_index, paragraph_text in enumerate(split_paragraphs(source_text), start=1):
        sentence_items = []
        sentence_translations = []

        for sentence_index, sentence_text in enumerate(split_sentences(paragraph_text), start=1):
            sentence_translation = translate_text_cached(sentence_text)
            sentence_translations.append(sentence_translation)
            words = []
            for word_index, token in enumerate(tokenize_sentence(sentence_text), start=1):
                words.append(build_word_entry(token, f"p{paragraph_index}s{sentence_index}w{word_index}"))
            if not words:
                continue
            sentence_items.append(
                {
                    "id": f"sentence-{paragraph_index}-{sentence_index}",
                    "hanzi": sentence_text,
                    "pinyin": build_sentence_pinyin(sentence_text),
                    "russian": sentence_translation,
                    "words": words,
                }
            )

        if not sentence_items:
            continue

        paragraphs.append(
            {
                "id": f"paragraph-{paragraph_index}",
                "paragraph_index": paragraph_index,
                "hanzi": paragraph_text,
                "pinyin": " ".join(sentence["pinyin"] for sentence in sentence_items),
                "russian": " ".join(sentence_translations),
                "sentences": sentence_items,
            }
        )

    if not paragraphs:
        raise ValueError("Не удалось собрать ни одного абзаца с пригодными предложениями и словами.")

    return {"title": title.strip() or "Новый китайский текст", "paragraphs": paragraphs}


def ensure_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def normalize_dataset(data: Dict[str, Any]) -> Dict[str, Any]:
    title = str(data.get("title") or "Новый китайский текст")
    paragraphs = []

    for paragraph_index, paragraph in enumerate(ensure_list(data.get("paragraphs")), start=1):
        sentences = []
        for sentence_index, sentence in enumerate(ensure_list(paragraph.get("sentences")), start=1):
            words = []
            for word_index, word in enumerate(ensure_list(sentence.get("words")), start=1):
                hanzi = str(word.get("hanzi") or "").strip()
                pinyin = str(word.get("pinyin") or "").strip()
                russian = str(word.get("russian") or "").strip()
                if not hanzi or not pinyin or not russian:
                    continue
                words.append(
                    {
                        "hanzi": hanzi,
                        "pinyin": pinyin,
                        "russian": russian,
                        "instance_id": f"p{paragraph_index}s{sentence_index}w{word_index}",
                    }
                )

            hanzi_sentence = str(sentence.get("hanzi") or "").strip()
            pinyin_sentence = str(sentence.get("pinyin") or "").strip()
            russian_sentence = str(sentence.get("russian") or "").strip()
            if not hanzi_sentence or not words:
                continue

            sentences.append(
                {
                    "id": f"sentence-{paragraph_index}-{sentence_index}",
                    "hanzi": hanzi_sentence,
                    "pinyin": pinyin_sentence,
                    "russian": russian_sentence,
                    "words": words,
                }
            )

        if not sentences:
            continue

        paragraph_hanzi = str(paragraph.get("hanzi") or "").strip() or " ".join(item["hanzi"] for item in sentences)
        paragraph_pinyin = str(paragraph.get("pinyin") or "").strip() or " ".join(item["pinyin"] for item in sentences)
        paragraph_russian = str(paragraph.get("russian") or "").strip() or " ".join(item["russian"] for item in sentences)

        paragraphs.append(
            {
                "id": f"paragraph-{paragraph_index}",
                "paragraph_index": paragraph_index,
                "hanzi": paragraph_hanzi,
                "pinyin": paragraph_pinyin,
                "russian": paragraph_russian,
                "sentences": sentences,
            }
        )

    if not paragraphs:
        raise ValueError("Модель не вернула пригодную структуру paragraphs/sentences/words.")

    return {"title": title, "paragraphs": paragraphs}

def dataset_stats(dataset: Dict[str, Any]) -> Dict[str, int]:
    paragraphs = dataset["paragraphs"]
    sentence_count = sum(len(paragraph["sentences"]) for paragraph in paragraphs)
    word_count = sum(len(sentence["words"]) for paragraph in paragraphs for sentence in paragraph["sentences"])
    unique_words = {
        f"{word['hanzi']}|{word['pinyin']}|{word['russian']}"
        for paragraph in paragraphs
        for sentence in paragraph["sentences"]
        for word in sentence["words"]
    }
    return {
        "paragraphs": len(paragraphs),
        "sentences": sentence_count,
        "words": word_count,
        "unique_words": len(unique_words),
    }


def game_html(dataset: Dict[str, Any], storage_key: str) -> str:
    payload = json.dumps(dataset, ensure_ascii=False).replace("</script>", "<\\/script>")
    storage_key = json.dumps(storage_key)
    return f"""
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <style>
    :root {{
      --bg: #f5efe4;
      --bg-soft: #efe5d3;
      --card: rgba(255, 252, 246, 0.94);
      --card-strong: #fffaf0;
      --ink: #1f2421;
      --muted: #6b6d63;
      --line: rgba(36, 42, 39, 0.12);
      --accent: #245c4f;
      --warm: #b7602b;
      --success: #1f8f58;
      --shadow: 0 18px 50px rgba(45, 34, 18, 0.12);
      --radius: 24px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "Noto Sans SC", "PingFang SC", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(255,255,255,0.68), transparent 28%),
        radial-gradient(circle at bottom right, rgba(36,92,79,0.16), transparent 26%),
        linear-gradient(145deg, #f8f1e3 0%, #eadcc2 48%, #e6d6bc 100%);
    }}
    .shell {{
      width: min(1400px, calc(100% - 20px));
      margin: 10px auto 24px;
    }}
    .hero, .stat, .reading, .board, .progress-box {{
      backdrop-filter: blur(14px);
      background: var(--card);
      border: 1px solid rgba(255,255,255,0.72);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }}
    .hero {{
      padding: 24px;
      display: flex;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 16px;
    }}
    .eyebrow {{
      margin: 0 0 8px;
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-size: 12px;
      color: var(--warm);
    }}
    .hero h1 {{
      margin: 0;
      font-family: Georgia, serif;
      font-size: clamp(28px, 4vw, 44px);
      line-height: 1.02;
    }}
    .hero p {{
      margin: 10px 0 0;
      line-height: 1.55;
      color: var(--muted);
    }}
    .actions {{
      min-width: 220px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      justify-content: center;
    }}
    button {{
      cursor: pointer;
      border: 0;
      border-radius: 999px;
      padding: 12px 16px;
      font-size: 14px;
      font-weight: 700;
      transition: transform .15s ease;
    }}
    button:hover {{ transform: translateY(-1px); }}
    .primary {{
      background: linear-gradient(135deg, #265f52 0%, #183e36 100%);
      color: white;
    }}
    .ghost {{
      background: rgba(255,250,240,.94);
      color: var(--ink);
      border: 1px solid rgba(31,36,33,.12);
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0,1fr));
      gap: 12px;
      margin-bottom: 16px;
    }}
    .stat {{ padding: 16px 18px; }}
    .label {{
      display: block;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .09em;
    }}
    .value {{
      font-size: 24px;
      line-height: 1.1;
      font-weight: 800;
    }}
    .progress-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0,1fr));
      gap: 12px;
      margin-bottom: 16px;
    }}
    .progress-box {{ padding: 14px 16px 16px; }}
    .progress-top {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 10px;
      color: var(--muted);
      font-size: 14px;
    }}
    .track {{
      height: 14px;
      overflow: hidden;
      border-radius: 999px;
      background: linear-gradient(90deg, rgba(36,92,79,.08), rgba(36,92,79,.18));
    }}
    .track.warm {{
      background: linear-gradient(90deg, rgba(183,96,43,.08), rgba(183,96,43,.18));
    }}
    .fill {{
      height: 100%;
      width: 0;
      border-radius: inherit;
      transition: width .25s ease;
      background: linear-gradient(90deg, #2e8d73 0%, #163b33 100%);
    }}
    .fill.warm {{
      background: linear-gradient(90deg, #cc7a3f 0%, #8e4519 100%);
    }}
    .reading {{
      padding: 22px;
      margin-bottom: 16px;
    }}
    .reading-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 16px;
    }}
    .reading-head h2 {{
      margin: 0;
      font-family: Georgia, serif;
      font-size: 28px;
    }}
    .muted {{
      color: var(--muted);
      font-size: 14px;
    }}
    .reading-grid-header {{
      display: grid;
      grid-template-columns: minmax(220px, 1.15fr) minmax(220px, 1.1fr) minmax(260px, 1.35fr);
      gap: 20px;
      padding: 0 0 10px;
      border-bottom: 1px solid var(--line);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .11em;
      color: var(--muted);
    }}
    .reading-item {{
      display: grid;
      grid-template-columns: minmax(220px, 1.15fr) minmax(220px, 1.1fr) minmax(260px, 1.35fr);
      gap: 20px;
      align-items: start;
      padding: 16px 0;
      border-top: 1px solid var(--line);
    }}
    .reading-grid-header + .reading-item {{
      border-top: 0;
    }}
    .reading-hanzi {{
      font-size: 26px;
      line-height: 1.35;
      font-weight: 700;
    }}
    .reading-pinyin {{
      color: var(--accent);
      font-size: 17px;
      line-height: 1.5;
      padding-top: 4px;
    }}
    .reading-russian {{
      color: var(--muted);
      line-height: 1.55;
      padding-top: 2px;
    }}
    .board {{
      padding: 20px;
    }}
    .board-top {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 16px;
    }}
    .board-top h3 {{
      margin: 0 0 8px;
      font-size: 24px;
    }}
    .hint {{
      margin: 0;
      color: var(--muted);
      line-height: 1.5;
    }}
    .status {{
      min-width: 260px;
      padding: 12px 14px;
      border-radius: 16px;
      background: var(--bg-soft);
      color: var(--accent);
      font-weight: 700;
      line-height: 1.4;
    }}
    .board-shell {{
      position: relative;
      display: grid;
      grid-template-columns: repeat(3, minmax(0,1fr));
      gap: 16px;
      min-height: 420px;
    }}
    .connections {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      overflow: visible;
    }}
    .lane {{
      position: relative;
      padding: 14px;
      border-radius: 20px;
      background: linear-gradient(180deg, rgba(255,255,255,.88), rgba(246,237,220,.92));
      border: 1px solid rgba(31,36,33,.08);
    }}
    .lane-title {{
      margin-bottom: 12px;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .11em;
      color: var(--muted);
    }}
    .lane-list {{
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .card {{
      position: relative;
      z-index: 2;
      padding: 12px 14px;
      border-radius: 16px;
      border: 1px solid rgba(31,36,33,.09);
      background: var(--card-strong);
      transition: transform .14s ease, background .14s ease, border-color .14s ease, box-shadow .14s ease;
      user-select: none;
      cursor: pointer;
    }}
    .card:hover {{ transform: translateY(-1px); }}
    .word-card {{ background: linear-gradient(180deg, #fffefb, #f7efe2); }}
    .pinyin-card {{ background: linear-gradient(180deg, #f6fdf9, #e8f6ef); }}
    .russian-card {{ background: linear-gradient(180deg, #fff8f1, #f6e8dc); }}
    .selected {{
      border-color: rgba(36,92,79,.45);
      box-shadow: 0 0 0 3px rgba(36,92,79,.15);
    }}
    .matched {{
      background: linear-gradient(180deg, #ecfff5, #daf7e7);
      border-color: rgba(31,143,88,.46);
      box-shadow: 0 0 0 3px rgba(31,143,88,.14);
    }}
    .wrong {{ animation: wrongPulse .35s ease; }}
    .idx {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 28px;
      height: 28px;
      margin-right: 10px;
      border-radius: 50%;
      font-size: 12px;
      font-weight: 800;
      background: rgba(31,36,33,.08);
    }}
    .body {{ display: inline; font-size: 18px; line-height: 1.45; }}
    .word-card .body {{ font-size: 24px; }}
    .banner {{
      margin-top: 16px;
      padding: 16px 18px;
      border-radius: 18px;
      background: linear-gradient(135deg, rgba(36,92,79,.12), rgba(31,143,88,.08));
      color: var(--accent);
      font-weight: 700;
    }}
    @keyframes wrongPulse {{
      0% {{ transform: scale(1); }}
      35% {{ transform: scale(1.02); background: #fff1ef; }}
      100% {{ transform: scale(1); }}
    }}
    @media (max-width: 1100px) {{
      .stats, .progress-grid {{ grid-template-columns: repeat(2, minmax(0,1fr)); }}
      .board-shell {{ grid-template-columns: 1fr; }}
      .connections {{ display: none; }}
    }}
    @media (max-width: 760px) {{
      .hero, .board-top, .reading-head {{ flex-direction: column; }}
      .actions, .status {{ min-width: 0; width: 100%; }}
      .stats, .progress-grid {{ grid-template-columns: 1fr; }}
      .reading-grid-header {{ display: none; }}
      .reading-item {{
        grid-template-columns: 1fr;
        gap: 8px;
      }}
      .reading-pinyin, .reading-russian {{
        padding-top: 0;
      }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div>
        <p class="eyebrow">Streamlit Visual Matching</p>
        <h1 id="heroTitle"></h1>
        <p>
          Сначала текст разбирается по предложениям, затем по абзацам, затем по случайным словам из всего текста.
          В каждом предложении участвуют все слова, которые вернула модель.
        </p>
      </div>
      <div class="actions">
        <button id="nextButton" class="primary">Начать разбор</button>
        <button id="resetButton" class="ghost">Сбросить прогресс</button>
      </div>
    </section>

    <section class="stats">
      <article class="stat"><span class="label">Текущий этап</span><strong id="stageLabel" class="value">—</strong></article>
      <article class="stat"><span class="label">Осталось слов</span><strong id="wordsLeftLabel" class="value">—</strong></article>
      <article class="stat"><span class="label">Точность</span><strong id="accuracyLabel" class="value">—</strong></article>
      <article class="stat"><span class="label">Разобрано блоков</span><strong id="unitsDoneLabel" class="value">—</strong></article>
    </section>

    <section class="progress-grid">
      <article class="progress-box">
        <div class="progress-top"><span>Прогресс этапа</span><span id="stageProgressText">—</span></div>
        <div class="track"><div id="stageProgressFill" class="fill"></div></div>
      </article>
      <article class="progress-box">
        <div class="progress-top"><span>Текущее задание</span><span id="unitProgressText">—</span></div>
        <div class="track warm"><div id="unitProgressFill" class="fill warm"></div></div>
      </article>
    </section>

    <section class="reading">
      <div class="reading-head">
        <h2 id="unitTitle">Подготовка к разбору</h2>
        <span id="unitMeta" class="muted">Сначала нажмите кнопку запуска</span>
      </div>
      <div id="readingText"></div>
    </section>

    <section class="board">
      <div class="board-top">
        <div>
          <h3>Соединяйте слово, pinyin и перевод</h3>
          <p class="hint">Сначала кликните по слову слева, затем по соответствующему pinyin и русскому переводу.</p>
        </div>
        <div id="selectionStatus" class="status">Нажмите «Начать разбор».</div>
      </div>

      <div id="boardShell" class="board-shell">
        <svg id="connections" class="connections"></svg>
        <div class="lane">
          <div class="lane-title">Слова</div>
          <div id="wordsLane" class="lane-list"></div>
        </div>
        <div class="lane">
          <div class="lane-title">Pinyin</div>
          <div id="pinyinLane" class="lane-list"></div>
        </div>
        <div class="lane">
          <div class="lane-title">Перевод</div>
          <div id="russianLane" class="lane-list"></div>
        </div>
      </div>
    </section>
  </div>

  <script>
    const DATA = {payload};
    const STORAGE_KEY = {storage_key};
    const stageNames = {{
      sentence: 'Разбор по предложениям',
      paragraph: 'Разбор по абзацам',
      random: 'Случайные слова из всего текста'
    }};

    const el = {{
      heroTitle: document.getElementById('heroTitle'),
      nextButton: document.getElementById('nextButton'),
      resetButton: document.getElementById('resetButton'),
      stageLabel: document.getElementById('stageLabel'),
      wordsLeftLabel: document.getElementById('wordsLeftLabel'),
      accuracyLabel: document.getElementById('accuracyLabel'),
      unitsDoneLabel: document.getElementById('unitsDoneLabel'),
      stageProgressText: document.getElementById('stageProgressText'),
      stageProgressFill: document.getElementById('stageProgressFill'),
      unitProgressText: document.getElementById('unitProgressText'),
      unitProgressFill: document.getElementById('unitProgressFill'),
      unitTitle: document.getElementById('unitTitle'),
      unitMeta: document.getElementById('unitMeta'),
      readingText: document.getElementById('readingText'),
      selectionStatus: document.getElementById('selectionStatus'),
      boardShell: document.getElementById('boardShell'),
      connections: document.getElementById('connections'),
      wordsLane: document.getElementById('wordsLane'),
      pinyinLane: document.getElementById('pinyinLane'),
      russianLane: document.getElementById('russianLane')
    }};

    function shuffle(array) {{
      const copy = [...array];
      for (let i = copy.length - 1; i > 0; i -= 1) {{
        const j = Math.floor(Math.random() * (i + 1));
        [copy[i], copy[j]] = [copy[j], copy[i]];
      }}
      return copy;
    }}

    function labelFromIndex(index, upper=false) {{
      let value = index;
      let label = '';
      while (value >= 0) {{
        label = String.fromCharCode((value % 26) + (upper ? 65 : 97)) + label;
        value = Math.floor(value / 26) - 1;
      }}
      return label;
    }}

    function defaultProgress() {{
      return {{
        attempts: 0,
        correct: 0,
        sentenceCursor: 0,
        paragraphCursor: 0,
        completedSentenceIds: [],
        completedParagraphIds: [],
        masteredWords: {{}},
        randomRounds: 0
      }};
    }}

    function loadProgress() {{
      try {{
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return defaultProgress();
        const parsed = JSON.parse(raw);
        return {{
          ...defaultProgress(),
          ...parsed,
          completedSentenceIds: Array.isArray(parsed.completedSentenceIds) ? parsed.completedSentenceIds : [],
          completedParagraphIds: Array.isArray(parsed.completedParagraphIds) ? parsed.completedParagraphIds : [],
          masteredWords: parsed.masteredWords || {{}}
        }};
      }} catch (e) {{
        return defaultProgress();
      }}
    }}

    function saveProgress(progress) {{
      localStorage.setItem(STORAGE_KEY, JSON.stringify(progress));
    }}

    function buildUnits() {{
      const sentenceUnits = [];
      const paragraphUnits = [];
      const uniqueMap = new Map();

      DATA.paragraphs.forEach((paragraph, paragraphIndex) => {{
        const paragraphWords = [];

        paragraph.sentences.forEach((sentence, sentenceIndex) => {{
          const words = sentence.words.map((word, wordIndex) => {{
            const item = {{
              ...word,
              key: `${{word.hanzi}}|${{word.pinyin}}|${{word.russian}}`,
              unitIndex: wordIndex,
              instanceId: `p${{paragraphIndex+1}}s${{sentenceIndex+1}}w${{wordIndex+1}}`,
              source: {{
                paragraphId: paragraph.id,
                paragraphIndex: paragraphIndex + 1,
                sentenceId: sentence.id,
                sentenceIndex: sentenceIndex + 1,
                sentenceHanzi: sentence.hanzi,
                sentencePinyin: sentence.pinyin,
                sentenceRussian: sentence.russian
              }}
            }};
            if (!uniqueMap.has(item.key)) {{
              uniqueMap.set(item.key, {{
                key: item.key,
                hanzi: item.hanzi,
                pinyin: item.pinyin,
                russian: item.russian,
                contexts: [item.source]
              }});
            }} else {{
              uniqueMap.get(item.key).contexts.push(item.source);
            }}
            return item;
          }});

          sentenceUnits.push({{
            id: sentence.id,
            kind: 'sentence',
            title: `Абзац ${{paragraphIndex+1}}, предложение ${{sentenceIndex+1}}`,
            meta: `${{words.length}} слов(а)`,
            readingItems: [{{
              hanzi: sentence.hanzi,
              pinyin: sentence.pinyin,
              russian: sentence.russian
            }}],
            words
          }});

          paragraphWords.push(...words.map((word, index) => ({{
            ...word,
            unitIndex: paragraphWords.length + index,
            instanceId: `${{word.instanceId}}-paragraph`
          }})));
        }});

        paragraphUnits.push({{
          id: paragraph.id,
          kind: 'paragraph',
          title: `Абзац ${{paragraphIndex+1}}`,
          meta: `${{paragraph.sentences.length}} предложений · ${{paragraphWords.length}} слов(а)`,
          readingItems: paragraph.sentences.map(sentence => ({{
            hanzi: sentence.hanzi,
            pinyin: sentence.pinyin,
            russian: sentence.russian
          }})),
          words: paragraphWords
        }});
      }});

      return {{
        sentenceUnits,
        paragraphUnits,
        uniqueWords: [...uniqueMap.values()]
      }};
    }}

    const built = buildUnits();
    const state = {{
      progress: loadProgress(),
      stage: 'sentence',
      currentUnit: null,
      matchedWords: new Set(),
      pinyinOrder: [],
      russianOrder: [],
      selection: {{ word: null, pinyin: null, russian: null }},
      unitComplete: false,
      wrongFlash: null
    }};

    function currentStage() {{
      if (state.progress.completedSentenceIds.length < built.sentenceUnits.length) return 'sentence';
      if (state.progress.completedParagraphIds.length < built.paragraphUnits.length) return 'paragraph';
      return 'random';
    }}

    function wordsMasteredCount() {{
      return built.uniqueWords.filter(word => (state.progress.masteredWords[word.key] || 0) > 0).length;
    }}

    function wordsLeft() {{
      return built.uniqueWords.length - wordsMasteredCount();
    }}

    function accuracy() {{
      return state.progress.attempts ? (state.progress.correct / state.progress.attempts) * 100 : 0;
    }}

    function nextIncomplete(units, completed, cursor) {{
      const done = new Set(completed);
      for (let i = Math.max(0, cursor); i < units.length; i += 1) {{
        if (!done.has(units[i].id)) return {{ index: i, unit: units[i] }};
      }}
      for (let i = 0; i < units.length; i += 1) {{
        if (!done.has(units[i].id)) return {{ index: i, unit: units[i] }};
      }}
      return {{ index: -1, unit: null }};
    }}

    function buildRandomUnit() {{
      const weighted = shuffle([...built.uniqueWords]).sort((a, b) => {{
        const sa = state.progress.masteredWords[a.key] || 0;
        const sb = state.progress.masteredWords[b.key] || 0;
        if (sa !== sb) return sa - sb;
        return Math.random() - 0.5;
      }});

      const sample = weighted.slice(0, Math.min(16, weighted.length)).map((word, index) => ({{
        hanzi: word.hanzi,
        pinyin: word.pinyin,
        russian: word.russian,
        key: word.key,
        unitIndex: index,
        instanceId: `random-${{state.progress.randomRounds}}-${{index}}`,
        source: word.contexts[0]
      }}));

      const readingItems = [];
      const seen = new Set();
      sample.forEach(word => {{
        const source = word.source;
        const key = source.sentenceId;
        if (!seen.has(key)) {{
          seen.add(key);
          readingItems.push({{
            hanzi: source.sentenceHanzi,
            pinyin: source.sentencePinyin,
            russian: source.sentenceRussian
          }});
        }}
      }});

      return {{
        id: `random-${{Date.now()}}`,
        kind: 'random',
        title: 'Случайные слова из всего текста',
        meta: `${{sample.length}} слов(а)`,
        readingItems,
        words: sample
      }};
    }}

    function getNextUnit() {{
      state.stage = currentStage();
      if (state.stage === 'sentence') return nextIncomplete(built.sentenceUnits, state.progress.completedSentenceIds, state.progress.sentenceCursor).unit;
      if (state.stage === 'paragraph') return nextIncomplete(built.paragraphUnits, state.progress.completedParagraphIds, state.progress.paragraphCursor).unit;
      return buildRandomUnit();
    }}

    function initUnit(unit) {{
      state.currentUnit = unit;
      state.selection = {{ word: null, pinyin: null, russian: null }};
      state.matchedWords = new Set();
      state.pinyinOrder = shuffle(unit.words.map((_, index) => index));
      state.russianOrder = shuffle(unit.words.map((_, index) => index));
      state.unitComplete = false;
      state.wrongFlash = null;
    }}

    function markWordSolved(word) {{
      state.progress.masteredWords[word.key] = (state.progress.masteredWords[word.key] || 0) + 1;
    }}

    function completeUnit() {{
      if (state.unitComplete || !state.currentUnit) return;
      state.unitComplete = true;
      if (state.stage === 'sentence') {{
        if (!state.progress.completedSentenceIds.includes(state.currentUnit.id)) {{
          state.progress.completedSentenceIds.push(state.currentUnit.id);
        }}
        const idx = built.sentenceUnits.findIndex(unit => unit.id === state.currentUnit.id);
        state.progress.sentenceCursor = Math.max(state.progress.sentenceCursor, idx + 1);
      }} else if (state.stage === 'paragraph') {{
        if (!state.progress.completedParagraphIds.includes(state.currentUnit.id)) {{
          state.progress.completedParagraphIds.push(state.currentUnit.id);
        }}
        const idx = built.paragraphUnits.findIndex(unit => unit.id === state.currentUnit.id);
        state.progress.paragraphCursor = Math.max(state.progress.paragraphCursor, idx + 1);
      }} else {{
        state.progress.randomRounds += 1;
      }}
      saveProgress(state.progress);
    }}

    function renderReading() {{
      if (!state.currentUnit) {{
        el.unitTitle.textContent = 'Подготовка к разбору';
        el.unitMeta.textContent = 'Сначала нажмите кнопку запуска';
        el.readingText.innerHTML = '';
        return;
      }}

      el.unitTitle.textContent = state.currentUnit.title;
      el.unitMeta.textContent = `${{stageNames[state.stage]}} · ${{state.currentUnit.meta}}`;
      el.readingText.innerHTML = '';

      if (state.currentUnit.readingItems.length) {{
        const header = document.createElement('div');
        header.className = 'reading-grid-header';
        header.innerHTML = `
          <div>Иероглифы</div>
          <div>Pinyin</div>
          <div>Перевод</div>
        `;
        el.readingText.appendChild(header);
      }}

      state.currentUnit.readingItems.forEach(item => {{
        const block = document.createElement('div');
        block.className = 'reading-item';
        block.innerHTML = `
          <div class="reading-hanzi">${{item.hanzi}}</div>
          <div class="reading-pinyin">${{item.pinyin}}</div>
          <div class="reading-russian">${{item.russian}}</div>
        `;
        el.readingText.appendChild(block);
      }});

      if (state.unitComplete) {{
        const banner = document.createElement('div');
        banner.className = 'banner';
        banner.textContent = 'Блок разобран полностью. Прочитайте его ещё раз и переходите дальше.';
        el.readingText.appendChild(banner);
      }}
    }}

    function updateStatus() {{
      if (!state.currentUnit) {{
        el.selectionStatus.textContent = 'Нажмите «Начать разбор».';
        return;
      }}
      if (state.unitComplete) {{
        el.selectionStatus.textContent = 'Блок завершён. Можно переходить к следующему.';
        return;
      }}
      const word = state.selection.word === null ? '—' : state.currentUnit.words[state.selection.word].hanzi;
      const pinyin = state.selection.pinyin === null ? '—' : state.currentUnit.words[state.selection.pinyin].pinyin;
      const russian = state.selection.russian === null ? '—' : state.currentUnit.words[state.selection.russian].russian;
      el.selectionStatus.textContent = `Слово: ${{word}} | Pinyin: ${{pinyin}} | Перевод: ${{russian}}`;
    }}

    function makeCard(type, wordIndex, label, text, extra='') {{
      const card = document.createElement('div');
      card.className = `card ${{type}}-card ${{extra}}`.trim();
      card.dataset.type = type;
      card.dataset.wordIndex = String(wordIndex);
      card.tabIndex = 0;
      card.innerHTML = `<span class="idx">${{label}}</span><span class="body">${{text}}</span>`;
      card.addEventListener('click', () => clickCard(type, wordIndex));
      card.addEventListener('keydown', event => {{
        if (event.key === 'Enter' || event.key === ' ') {{
          event.preventDefault();
          clickCard(type, wordIndex);
        }}
      }});
      return card;
    }}

    function renderBoard() {{
      el.wordsLane.innerHTML = '';
      el.pinyinLane.innerHTML = '';
      el.russianLane.innerHTML = '';
      el.connections.innerHTML = '';
      if (!state.currentUnit) return;

      const wrongSet = state.wrongFlash ? new Set(state.wrongFlash) : new Set();

      state.currentUnit.words.forEach((word, index) => {{
        const classes = [];
        if (state.matchedWords.has(index)) classes.push('matched');
        if (state.selection.word === index) classes.push('selected');
        if (wrongSet.has(`word-${{index}}`)) classes.push('wrong');
        el.wordsLane.appendChild(makeCard('word', index, String(index + 1), word.hanzi, classes.join(' ')));
      }});

      state.pinyinOrder.forEach((wordIndex, index) => {{
        const word = state.currentUnit.words[wordIndex];
        const classes = [];
        if (state.matchedWords.has(wordIndex)) classes.push('matched');
        if (state.selection.pinyin === wordIndex) classes.push('selected');
        if (wrongSet.has(`pinyin-${{wordIndex}}`)) classes.push('wrong');
        el.pinyinLane.appendChild(makeCard('pinyin', wordIndex, labelFromIndex(index, false), word.pinyin, classes.join(' ')));
      }});

      state.russianOrder.forEach((wordIndex, index) => {{
        const word = state.currentUnit.words[wordIndex];
        const classes = [];
        if (state.matchedWords.has(wordIndex)) classes.push('matched');
        if (state.selection.russian === wordIndex) classes.push('selected');
        if (wrongSet.has(`russian-${{wordIndex}}`)) classes.push('wrong');
        el.russianLane.appendChild(makeCard('russian', wordIndex, labelFromIndex(index, true), word.russian, classes.join(' ')));
      }});

      requestAnimationFrame(drawConnections);
    }}

    function pathBetween(x1, y1, x2, y2) {{
      const dx = (x2 - x1) * 0.42;
      return `M ${{x1}} ${{y1}} C ${{x1 + dx}} ${{y1}}, ${{x2 - dx}} ${{y2}}, ${{x2}} ${{y2}}`;
    }}

    function drawConnections() {{
      el.connections.innerHTML = '';
      if (!state.currentUnit || window.innerWidth <= 1100) return;

      const rect = el.boardShell.getBoundingClientRect();
      el.connections.setAttribute('viewBox', `0 0 ${{rect.width}} ${{rect.height}}`);

      state.matchedWords.forEach(wordIndex => {{
        const wordEl = el.boardShell.querySelector(`.word-card[data-word-index="${{wordIndex}}"]`);
        const pinyinEl = el.boardShell.querySelector(`.pinyin-card[data-word-index="${{wordIndex}}"]`);
        const russianEl = el.boardShell.querySelector(`.russian-card[data-word-index="${{wordIndex}}"]`);
        if (!wordEl || !pinyinEl || !russianEl) return;

        const wr = wordEl.getBoundingClientRect();
        const pr = pinyinEl.getBoundingClientRect();
        const rr = russianEl.getBoundingClientRect();

        const x1 = wr.right - rect.left;
        const y1 = wr.top - rect.top + wr.height / 2;
        const x2 = pr.left - rect.left;
        const y2 = pr.top - rect.top + pr.height / 2;
        const x3 = rr.left - rect.left;
        const y3 = rr.top - rect.top + rr.height / 2;

        const path1 = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path1.setAttribute('d', pathBetween(x1, y1, x2, y2));
        path1.setAttribute('fill', 'none');
        path1.setAttribute('stroke', '#1f8f58');
        path1.setAttribute('stroke-width', '4');
        path1.setAttribute('stroke-linecap', 'round');

        const path2 = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path2.setAttribute('d', pathBetween(x2, y2, x3, y3));
        path2.setAttribute('fill', 'none');
        path2.setAttribute('stroke', '#1f8f58');
        path2.setAttribute('stroke-width', '4');
        path2.setAttribute('stroke-linecap', 'round');

        el.connections.append(path1, path2);
      }});
    }}

    function renderStats() {{
      const stage = currentStage();
      el.stageLabel.textContent = stageNames[stage];
      el.wordsLeftLabel.textContent = `${{wordsLeft()}} / ${{built.uniqueWords.length}}`;
      el.accuracyLabel.textContent = `${{accuracy().toFixed(1)}}%`;

      let done = 0;
      let total = 1;
      if (stage === 'sentence') {{
        done = state.progress.completedSentenceIds.length;
        total = built.sentenceUnits.length;
        el.unitsDoneLabel.textContent = `${{done}} / ${{total}} предложений`;
      }} else if (stage === 'paragraph') {{
        done = state.progress.completedParagraphIds.length;
        total = built.paragraphUnits.length;
        el.unitsDoneLabel.textContent = `${{done}} / ${{total}} абзацев`;
      }} else {{
        done = state.progress.randomRounds;
        total = Math.max(1, Math.ceil(built.uniqueWords.length / 16));
        el.unitsDoneLabel.textContent = `${{done}} раунд(ов)`;
      }}

      const stagePercent = stage === 'random'
        ? (wordsMasteredCount() / Math.max(1, built.uniqueWords.length)) * 100
        : (done / Math.max(1, total)) * 100;

      el.stageProgressText.textContent = stage === 'random'
        ? `${{wordsMasteredCount()}} из ${{built.uniqueWords.length}} слов закреплено`
        : `${{done}} из ${{total}}`;
      el.stageProgressFill.style.width = `${{Math.min(100, stagePercent)}}%`;

      if (!state.currentUnit) {{
        el.unitProgressText.textContent = '0 из 0';
        el.unitProgressFill.style.width = '0%';
      }} else {{
        const solved = state.matchedWords.size;
        const totalWords = state.currentUnit.words.length;
        el.unitProgressText.textContent = `${{solved}} из ${{totalWords}}`;
        el.unitProgressFill.style.width = `${{(solved / Math.max(1, totalWords)) * 100}}%`;
      }}
    }}

    function renderButton() {{
      if (!state.currentUnit) {{
        el.nextButton.disabled = false;
        el.nextButton.textContent = 'Начать разбор';
        return;
      }}
      if (!state.unitComplete) {{
        el.nextButton.disabled = true;
        el.nextButton.textContent = 'Сначала завершите текущий блок';
        return;
      }}
      const stage = currentStage();
      if (stage === 'sentence') el.nextButton.textContent = 'Следующее предложение';
      else if (stage === 'paragraph') el.nextButton.textContent = state.stage === 'sentence' ? 'Перейти к разбору по абзацам' : 'Следующий абзац';
      else el.nextButton.textContent = state.stage === 'random' ? 'Следующий случайный набор' : 'Перейти к случайным словам';
      el.nextButton.disabled = false;
    }}

    function renderAll() {{
      el.heroTitle.textContent = DATA.title;
      renderStats();
      renderReading();
      updateStatus();
      renderBoard();
      renderButton();
    }}

    function clearWrongFlash() {{
      state.wrongFlash = null;
      renderBoard();
    }}

    function evaluateSelection() {{
      const {{ word, pinyin, russian }} = state.selection;
      if (word === null || pinyin === null || russian === null) return;

      state.progress.attempts += 1;
      const ok = word === pinyin && word === russian;
      if (ok) {{
        state.progress.correct += 1;
        state.matchedWords.add(word);
        markWordSolved(state.currentUnit.words[word]);
        state.selection = {{ word: null, pinyin: null, russian: null }};
        saveProgress(state.progress);
        if (state.matchedWords.size === state.currentUnit.words.length) completeUnit();
        renderAll();
        return;
      }}

      state.wrongFlash = [`word-${{word}}`, `pinyin-${{pinyin}}`, `russian-${{russian}}`];
      state.selection = {{ word: null, pinyin: null, russian: null }};
      saveProgress(state.progress);
      renderAll();
      setTimeout(clearWrongFlash, 340);
    }}

    function clickCard(type, wordIndex) {{
      if (!state.currentUnit || state.unitComplete) return;
      if (state.matchedWords.has(wordIndex)) return;
      state.selection[type] = state.selection[type] === wordIndex ? null : wordIndex;
      renderAll();
      evaluateSelection();
    }}

    function loadNextUnit() {{
      const unit = getNextUnit();
      if (!unit) return;
      initUnit(unit);
      renderAll();
    }}

    el.nextButton.addEventListener('click', () => {{
      if (!state.currentUnit || state.unitComplete) loadNextUnit();
    }});

    el.resetButton.addEventListener('click', () => {{
      const ok = window.confirm('Сбросить прогресс этой игры?');
      if (!ok) return;
      state.progress = defaultProgress();
      saveProgress(state.progress);
      state.currentUnit = null;
      state.matchedWords = new Set();
      state.pinyinOrder = [];
      state.russianOrder = [];
      state.selection = {{ word: null, pinyin: null, russian: null }};
      state.unitComplete = false;
      state.wrongFlash = null;
      renderAll();
    }});

    window.addEventListener('resize', () => requestAnimationFrame(drawConnections));
    renderAll();
  </script>
</body>
</html>
"""


def main() -> None:
    st.title("Chinese Visual Matching Builder")
    st.caption("Бесплатный режим: загрузите китайский текст, вставьте специальный формат или готовый JSON, затем сразу играйте в визуальный режим сопоставления.")

    with st.sidebar:
        st.header("Режим")
        mode = st.radio(
            "Источник данных",
            options=["Бесплатная автогенерация", "Специальный формат", "Загрузить готовый JSON"],
            index=0,
        )
        st.markdown(
            "- Бесплатный режим использует `jieba` для сегментации.\n"
            "- `pypinyin` строит pinyin локально.\n"
            "- `deep-translator` делает бесплатный перевод без API key.\n"
            "- Специальный формат можно готовить вручную или через LLM.\n"
            "- Сначала строится разбор по предложениям.\n"
            "- Затем разбор по абзацам.\n"
            "- Потом случайные слова из всего текста."
        )

    with st.expander("Инструкция для LLM: как готовить специальный формат", expanded=False):
        prompt_text = llm_prompt_for_special_format()
        template_text = special_format_template()
        st.markdown(
            "Вставьте в LLM чистый китайский текст и попросите вернуть не JSON, а специальный формат ниже. "
            "Этот режим нужен, когда вы хотите вручную контролировать сегментацию, pinyin и перевод."
        )
        st.text_area(
            "Готовый промпт для LLM",
            value=prompt_text,
            height=360,
            key="llm_prompt_preview",
        )
        st.text_area(
            "Шаблон специального формата",
            value=template_text,
            height=360,
            key="special_format_template_preview",
        )
        dl1, dl2 = st.columns(2)
        dl1.download_button(
            "Скачать промпт для LLM",
            data=prompt_text.encode("utf-8"),
            file_name="llm_prompt_for_special_format.txt",
            mime="text/plain",
            use_container_width=True,
        )
        dl2.download_button(
            "Скачать шаблон формата",
            data=template_text.encode("utf-8"),
            file_name="special_format_template.txt",
            mime="text/plain",
            use_container_width=True,
        )

    presets = special_format_presets()
    uploaded = st.file_uploader("Загрузите `.txt` или `.md`", type=["txt", "md"]) if mode == "Бесплатная автогенерация" else None
    uploaded_json = st.file_uploader("Загрузите готовый JSON структуры", type=["json"]) if mode == "Загрузить готовый JSON" else None
    special_text = ""
    title = st.text_input("Название набора", value=st.session_state.get("dataset_title", "Новый китайский текст"))
    source_text = ""
    if mode == "Бесплатная автогенерация":
        source_text = st.text_area(
            "Или вставьте китайский текст сюда",
            value=st.session_state.get("source_text", ""),
            height=220,
            placeholder="Вставьте китайский текст. Лучше сохранять абзацы и переносы строк.",
        )
    elif mode == "Специальный формат":
        preset_name = st.selectbox(
            "Готовый шаблон",
            options=list(presets.keys()),
            index=1 if "Диалог Иван — профессор Лю" in presets else 0,
            key="special_format_preset_name",
        )
        if st.session_state.get("special_format_loaded_preset") != preset_name:
            st.session_state["special_format_text"] = presets[preset_name]
            st.session_state["special_format_loaded_preset"] = preset_name
        special_text = st.text_area(
            "Вставьте текст в специальном формате",
            key="special_format_text",
            height=420,
            placeholder="TITLE: ...\n\nPARAGRAPH\nHANZI: ...",
        )

    if uploaded is not None:
        source_text = uploaded.read().decode("utf-8")
        st.session_state["source_text"] = source_text
    elif mode == "Бесплатная автогенерация":
        st.session_state["source_text"] = source_text

    col_a, col_b, col_c = st.columns([1, 1, 2])
    with col_a:
        generate_clicked = st.button(
            "Сгенерировать игру" if mode == "Бесплатная автогенерация" else ("Загрузить JSON" if mode == "Загрузить готовый JSON" else "Построить из формата"),
            type="primary",
            use_container_width=True,
        )
    with col_b:
        clear_clicked = st.button("Очистить", use_container_width=True)

    if clear_clicked:
        st.session_state.pop("generated_dataset", None)
        st.session_state.pop("source_text", None)
        st.session_state.pop("dataset_title", None)
        st.session_state.pop("special_format_text", None)
        st.session_state.pop("special_format_loaded_preset", None)
        st.session_state.pop("special_format_preset_name", None)
        st.rerun()

    st.session_state["dataset_title"] = title

    if generate_clicked:
        if mode == "Загрузить готовый JSON":
            if uploaded_json is None:
                st.error("Сначала загрузите JSON-файл со структурой игры.")
            else:
                try:
                    dataset = normalize_dataset(json.loads(uploaded_json.read().decode("utf-8")))
                except Exception as exc:
                    st.exception(exc)
                else:
                    st.session_state["generated_dataset"] = dataset
        elif mode == "Специальный формат":
            if not special_text.strip():
                st.error("Сначала вставьте текст в специальном формате.")
            else:
                try:
                    dataset = parse_special_format(special_text)
                except Exception as exc:
                    st.exception(exc)
                else:
                    st.session_state["generated_dataset"] = dataset
        else:
            if not source_text.strip():
                st.error("Сначала загрузите или вставьте китайский текст.")
            else:
                with st.spinner("Бесплатный режим разбирает текст, строит pinyin, перевод и пословную структуру..."):
                    try:
                        dataset = generate_dataset_free(source_text.strip(), title)
                    except Exception as exc:
                        st.exception(exc)
                    else:
                        st.session_state["generated_dataset"] = dataset

    dataset = st.session_state.get("generated_dataset")
    if not dataset:
        st.info("После генерации или загрузки JSON здесь появятся структура текста, статистика и сама визуальная игра.")
        return

    stats = dataset_stats(dataset)
    stat_1, stat_2, stat_3, stat_4 = st.columns(4)
    stat_1.metric("Абзацы", stats["paragraphs"])
    stat_2.metric("Предложения", stats["sentences"])
    stat_3.metric("Все слова", stats["words"])
    stat_4.metric("Уникальные слова", stats["unique_words"])

    with st.expander("Предпросмотр структуры", expanded=False):
        st.json(dataset, expanded=2)

    json_blob = json.dumps(dataset, ensure_ascii=False, indent=2)
    st.download_button(
        "Скачать JSON структуры",
        data=json_blob.encode("utf-8"),
        file_name="generated_chinese_game.json",
        mime="application/json",
        use_container_width=True,
    )

    storage_key = "streamlit-chinese-game-" + hashlib.sha1(json_blob.encode("utf-8")).hexdigest()
    components.html(game_html(dataset, storage_key), height=1800, scrolling=True)


if __name__ == "__main__":
    main()
