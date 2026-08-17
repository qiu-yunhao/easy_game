from __future__ import annotations

import unittest

from StoryTemplate.TemplateSchema import (
    StyleBible, CharacterArchetype, PlotBeat, PlotSkeletonNode,
    STYLE_BIBLE_RESPONSE_SCHEMA, CHARACTER_ARCHETYPE_RESPONSE_SCHEMA,
    PLOT_BEAT_RESPONSE_SCHEMA, PLOT_SKELETON_RESPONSE_SCHEMA,
    CHUNK_SIGNAL_RESPONSE_SCHEMA,
    empty_style_bible,
)


class SchemaShapeTests(unittest.TestCase):
    def test_style_bible_has_all_fields(self):
        sb: StyleBible = {
            "narrative_voice": "第三人称全知", "tone_tags": ["古雅", "诙谐"],
            "prose_rhythm": "长短交错", "signature_devices": ["环境白描"],
            "world_premise": "江湖庙堂交织", "cultivation_system": "无",
            "factions": ["天地会"], "key_locations": ["扬州"],
            "world_rules": ["不可泄露身份"], "lexicon": ["韦小宝"],
        }
        self.assertEqual(set(StyleBible.__annotations__), set(sb))

    def test_empty_style_bible_is_valid_default(self):
        sb = empty_style_bible()
        self.assertEqual(sb["narrative_voice"], "")
        self.assertEqual(sb["tone_tags"], [])
        self.assertEqual(set(StyleBible.__annotations__), set(sb))

    def test_response_schemas_are_json_object_type(self):
        for schema in (
            STYLE_BIBLE_RESPONSE_SCHEMA, CHARACTER_ARCHETYPE_RESPONSE_SCHEMA,
            PLOT_BEAT_RESPONSE_SCHEMA, PLOT_SKELETON_RESPONSE_SCHEMA,
            CHUNK_SIGNAL_RESPONSE_SCHEMA,
        ):
            self.assertEqual(schema["type"], "json_schema")
            self.assertIn("json_schema", schema)

    def test_character_and_beat_and_node_fields(self):
        self.assertEqual(
            set(CharacterArchetype.__annotations__),
            {"name", "role_summary", "persona", "speech_style", "secrets",
             "signature_relations", "suggested_layer"},
        )
        self.assertEqual(
            set(PlotBeat.__annotations__),
            {"beat_id", "label", "tags", "summary", "dramatic_function", "reusable_conflict"},
        )
        self.assertEqual(
            set(PlotSkeletonNode.__annotations__),
            {"node_id", "order_index", "title", "event_summary",
             "preconditions", "maps_to_chapter_hint"},
        )


if __name__ == "__main__":
    unittest.main()
