from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class AuthPayload(BaseModel):
    # Reject unexpected keys rather than ignoring them. A stray field is a
    # client bug or someone probing, and silence hides both.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalise_email(cls, value: str) -> str:
        # Stored and compared as an exact string, so the case a person happens
        # to type must not create a second account or block a sign in.
        return value.lower()


class AuthResponse(BaseModel):
    access_token: str
    token_type: str
    user: dict