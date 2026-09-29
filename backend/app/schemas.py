from datetime import timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator


class RegisterData(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    student_id: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(min_length=8, max_length=128)
    consent: bool

    @field_validator("name", "student_id", "username", mode="before")
    @classmethod
    def normalize(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("consent")
    @classmethod
    def consent_required(cls, value):
        if not value:
            raise ValueError("需要同意照片用于身份核验")
        return value


class LoginData(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class EventData(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @field_validator("name", mode="before")
    @classmethod
    def name_not_blank(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def window(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("结束时间必须晚于开始时间")
        self.starts_at = self.starts_at.astimezone(timezone.utc)
        self.ends_at = self.ends_at.astimezone(timezone.utc)
        return self


class UserState(BaseModel):
    status: Literal["active", "disabled"]
