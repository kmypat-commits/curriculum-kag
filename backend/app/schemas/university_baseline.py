from pydantic import BaseModel, ConfigDict, Field


class BaselineColumnMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    credits: str = Field(min_length=1, max_length=200)


class BaselineRowMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_row: int = Field(ge=2)
    course_id: int = Field(ge=1)


class BaselineMappingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[BaselineRowMapping] = Field(min_length=1, max_length=5000)
