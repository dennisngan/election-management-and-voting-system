"""Shared input rules for named election configuration records."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NamedInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)

    @field_validator("name")
    @classmethod
    def meaningful_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A name is required")
        return value


class CodedInput(NamedInput):
    code: str = Field(min_length=1, max_length=32)

    @field_validator("code")
    @classmethod
    def meaningful_code(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A code is required")
        return value
