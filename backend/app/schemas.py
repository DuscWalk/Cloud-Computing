from pydantic import BaseModel, Field, field_validator


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
