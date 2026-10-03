from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from fastapi import status

from .config import settings
from .exceptions import APIException

ALGORITHM = settings.algorithm
JWT_SECRET_KEY = settings.secret_jwt_key
if not JWT_SECRET_KEY:
    raise APIException("Missing JWT secret key")


def create_access_token(claims: dict):
    return create_token(claims, token_type="access", expires_in=timedelta(minutes=15))


def create_token(claims: dict, *, token_type: str, expires_in: timedelta) -> str:
    to_encode = claims.copy()
    now = datetime.now(timezone.utc)
    to_encode.update(
        {
            "aud": settings.jwt_audience,
            "exp": now + expires_in,
            "iat": now,
            "iss": settings.jwt_issuer,
            "jti": uuid4().hex,
            "nbf": now,
            "typ": token_type,
        }
    )
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str, *, token_type: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[ALGORITHM],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={
                "require": ["aud", "exp", "iat", "iss", "jti", "nbf", "sub", "typ"]
            },
        )
        if payload.get("typ") != token_type:
            raise jwt.InvalidTokenError("Unexpected token type")
        return payload
    except jwt.ExpiredSignatureError:
        raise APIException("JWT token has expired", status.HTTP_401_UNAUTHORIZED)
    except jwt.InvalidTokenError:
        raise APIException("Invalid JWT token", status.HTTP_401_UNAUTHORIZED)


def decode_access_token(access_token: str) -> dict:
    return decode_token(access_token, token_type="access")
