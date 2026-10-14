"""Request bodies of the web API (design §21.6). Extra keys are refused.

Limits are deliberately tight: the byte cap of 1 MiB (security.py) is enforced
while streaming; these models bound the decoded fields as well. Core remains the
final authority for every rule (tags, types, kinds, hashes).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from gregraph.core.models import LinkType

TYPE_NAME = r"^[a-z][a-z0-9-]{0,63}$"
TAG = r"^[a-z0-9-]{1,64}$"
DOC_ID = r"^[A-Za-z0-9-]{1,32}$"
BASE_HASH = r"^sha256:[0-9a-f]{64}$"
MAX_TAGS = 50
MAX_TEXT_CHARS = 1_000_000

TypeName = Annotated[str, StringConstraints(pattern=TYPE_NAME)]
Tag = Annotated[str, StringConstraints(pattern=TAG)]
DocId = Annotated[str, StringConstraints(pattern=DOC_ID)]
Title = Annotated[
    str,
    StringConstraints(min_length=1, max_length=200, pattern=r"^[^\r\n\x00]+$"),
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=False)


class CreateDocument(_Strict):
    type: TypeName
    title: Title
    tags: list[Tag] = Field(max_length=MAX_TAGS)


class PatchMeta(_Strict):
    tags: list[Tag] = Field(max_length=MAX_TAGS)


class BodyUpdate(_Strict):
    text: str = Field(max_length=MAX_TEXT_CHARS)
    base_hash: Annotated[str, StringConstraints(pattern=BASE_HASH)]


class LinkCreate(_Strict):
    source: DocId
    type: LinkType
    target: DocId
