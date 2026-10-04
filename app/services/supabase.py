from functools import lru_cache

from supabase import Client, create_client

from app.core.config import settings


@lru_cache
def get_supabase_client() -> Client:
    """Return the trusted backend client for Supabase Storage operations."""
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
