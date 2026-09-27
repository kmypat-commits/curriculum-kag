"""Opt-in methodist requirements; client cannot supply an approval signature."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class CoreBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    lo_codes: list[str] = Field(default_factory=list, max_length=40)
    requirement: Literal["preferred", "required"] = "preferred"
    origin: Literal["system_suggestion", "methodist"] = "methodist"
    min_courses: int = Field(default=1, ge=1, le=5)
    min_credits: int = Field(default=0, ge=0, le=244)
    accepted_course_ids: list[int] = Field(default_factory=list, max_length=100)

    @field_validator("accepted_course_ids")
    @classmethod
    def valid_ids(cls, ids):
        if any(i <= 0 for i in ids) or len(set(ids)) != len(ids):
            raise ValueError("Course IDs must be unique and positive")
        return ids


class CurriculumRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    schema_version: Literal[1] = 1
    required_course_ids: list[int] = Field(default_factory=list, max_length=30)
    core_blocks: list[CoreBlock] = Field(default_factory=list, max_length=12)

    @field_validator("required_course_ids")
    @classmethod
    def valid_ids(cls, ids):
        return CoreBlock.valid_ids(ids)

    @field_validator("core_blocks")
    @classmethod
    def unique_blocks(cls, blocks):
        if len({b.id for b in blocks}) != len(blocks):
            raise ValueError("Block IDs must be unique")
        return blocks
