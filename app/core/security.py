from datetime import datetime, timedelta, timezone

import jwt
from fastapi import status

from .config import settings
from .exceptions import APIException

ALGORITHM = settings.algorithm
JWT_SECRET_KEY = settings.secret_jwt_key
ACCESS_TOKEN_EXPIRE_MINS = 15

if not JWT_SECRET_KEY:
    raise APIException("Missing JWT secret key")


def create_access_token(claims: dict):
    to_encode = claims.copy()
    expire_time = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINS
    )
    to_encode.update({"exp": expire_time})
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(access_token: str):
    try:
        payload = jwt.decode(access_token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise APIException("JWT token has expired", status.HTTP_401_UNAUTHORIZED)
    except jwt.InvalidTokenError:
        raise APIException("Invalid JWT token", status.HTTP_401_UNAUTHORIZED)
