from __future__ import annotations

from datetime import datetime
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, field_validator


class UserRegister(BaseModel):
    email:     str
    password:  str
    full_name: str | None = None

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        try:
            info = validate_email(v, check_deliverability=False)
            return info.normalized
        except EmailNotValidError as e:
            raise ValueError(str(e))

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Пароль має бути не менше 8 символів")
        return v


class UserLogin(BaseModel):
    email:    str
    password: str


class UserOut(BaseModel):
    id:         UUID
    email:      str
    role:       str
    status:     str
    full_name:  str | None
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type:   str = "bearer"
