from Actor.ActorFormatter import _quote_spoken_text, compose_resolved_act_content
from web_session import _build_prompt_templates, _strip_trailing_sentence_marks


def test_strip_trailing_sentence_marks_removes_terminal_punctuation() -> None:
    assert _strip_trailing_sentence_marks("看清局势。") == "看清局势"
    assert _strip_trailing_sentence_marks("稳住局面！？") == "稳住局面"
    assert _strip_trailing_sentence_marks("", "推进当前场景") == "推进当前场景"


def test_build_prompt_templates_avoids_duplicate_sentence_marks() -> None:
    templates = _build_prompt_templates(
        {
            "scene_goal": "看清局势，找出下一步。",
            "chapter_goal": "稳住局面。",
            "beat_goal": "先和眼前人搭上线。",
            "scene_location": "山门前",
        }
    )

    fills = [item["fill"] for item in templates]
    assert all("。。" not in fill for fill in fills)
    assert all("”。。" not in fill for fill in fills)
    assert fills[0].endswith("。")
    assert "如何看清局势，找出下一步。" in fills[0]


def test_quote_spoken_text_appends_missing_closing_quote() -> None:
    assert _quote_spoken_text("“先别动。") == "“先别动。”"
    assert compose_resolved_act_content("speak", "“先别动。", "") == "“先别动。”"


def test_quote_spoken_text_prepends_missing_opening_quote() -> None:
    assert _quote_spoken_text('先别动。”') == "“先别动。”"
