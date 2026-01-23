from pydantic import BaseModel, EmailStr, constr


class AuthPayload(BaseModel):
    email: EmailStr
    password: constr(min_length=8, max_length=128)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str
    user: dict
