from __future__ import annotations

from typing import Any

from db import Database
from embedding import BgeEmbeddingModel
from vectordb import PgVectorStore
from StoryTemplate.StoryTemplateService import StoryTemplateService
from StoryTemplate.TemplateChunker import TemplateChunker
from StoryTemplate.TemplateClustering import TemplateClustering
from StoryTemplate.TemplateExtractAgent import TemplateExtractAgent
from StoryTemplate.TemplateRepository import TemplateRepository

"""装配 StoryTemplateService，注入默认真实现（延迟构造，测试可传 fake client）。"""


def build_story_template_service(
    *, mysql_url: str, pg_url: str, client: Any | None = None,
    embedding: Any | None = None,
) -> StoryTemplateService:
    if embedding is None:
        embedding = BgeEmbeddingModel()
    vector_store = PgVectorStore(pg_url)
    repository = TemplateRepository(Database(mysql_url))
    repository.create_all()
    extract_agent = TemplateExtractAgent(client=client)
    return StoryTemplateService(
        chunker=TemplateChunker(),
        extract_agent=extract_agent,
        clustering=TemplateClustering(embedding),
        repository=repository,
        vector_store=vector_store,
        embedding=embedding,
    )
