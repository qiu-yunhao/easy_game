"""通用小说情节提取脚本:把任意中文小说跑通「切块→提炼→聚类→归并→入库」全链路。

模板是全局共享资产(user_id 仅作归属标记),换任意小说只需改 --path/--title。
默认用鹿鼎记.txt 作示例语料验证,功能不绑定该书。

用法:
  HF_ENDPOINT=https://hf-mirror.com /Users/qiuyunhao.1/miniconda3/bin/python3 \
    scripts/extract_novel_template.py --path docs/鹿鼎记.txt --title 鹿鼎记 --max-chunks 3
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from env_bootstrap import ensure_environment
from StoryTemplate.factory import build_story_template_service
from StoryTemplate.TemplateChunker import TemplateChunker


def main() -> int:
    parser = argparse.ArgumentParser(description="通用小说情节模板提取")
    parser.add_argument("--path", default="docs/鹿鼎记.txt",
                        help="小说文本路径(任意中文小说)")
    parser.add_argument("--title", default="",
                        help="模板来源标题;留空则用文件名")
    parser.add_argument("--user-id", type=int, default=0,
                        help="归属者 user_id(默认 0=平台/官方;只存不过滤)")
    parser.add_argument("--max-chunks", type=int, default=3,
                        help="只提取前 N 块以控制 LLM 成本/耗时;0 表示全文")
    args = parser.parse_args()

    ensure_environment(require_bge=True)  # LLM/MySQL/PG/bge 全需

    title = args.title or os.path.splitext(os.path.basename(args.path))[0]
    with open(args.path, encoding="utf-8") as f:
        text = f.read()
    print(f"[1] 读入 {args.path}: {len(text)} 字 (标题={title!r})")

    if args.max_chunks > 0:
        chunks = TemplateChunker().chunk(text)
        print(f"[2] 切块总数 {len(chunks)},仅取前 {args.max_chunks} 块提取")
        text = "\n".join(c.text for c in chunks[:args.max_chunks])

    service = build_story_template_service(
        mysql_url=os.environ["MYSQL_URL"], pg_url=os.environ["PG_URL"], client=None,
    )
    print("[3] 服务已装配 (真 bge + 真 pgvector + 真 MySQL + 真 DeepSeek),开始提取...")

    tid = service.import_novel(source_title=title, text=text, user_id=args.user_id)
    print(f"[4] 提取完成,template_id={tid}")

    sb = service.get_style_bible(tid)
    print(f"\n[风格圣经] 叙事视角={sb['narrative_voice']!r}")
    print(f"    语气标签={sb['tone_tags']}")
    print(f"    势力={sb['factions']}  地点={sb['key_locations']}")

    chars = service._repo.get_characters(tid)
    print(f"\n[角色原型] {len(chars)} 个:")
    for c in chars[:5]:
        print(f"    - {c['name']}({c['suggested_layer']}): {c['role_summary']}")

    beats = service.suggest_plot_beats(tid, query="", top_k=10)
    print(f"\n[情节桥段] {len(beats)} 条:")
    for b in beats[:5]:
        print(f"    - {b['label']} [{'/'.join(b['tags'])}]: {b['summary']}")

    all_nodes = service._repo.get_skeleton(tid)
    print(f"\n[主线骨架] {len(all_nodes)} 节点:")
    for n in all_nodes[:5]:
        print(f"    #{n['order_index']} {n['title']}: {n['event_summary']}")

    passages = service.search_style_passages(tid, query=title, top_k=2)
    print(f"\n[风格片段检索] {title!r} → {len(passages)} 段命中")

    print(f"\n[结果] {title} 章节情节提取全链路跑通。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
