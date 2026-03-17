"""
GCP Secret Manager Utility
Provides secure secret retrieval with local .env fallback for development.
"""

import os
import logging
from typing import Optional

logger = logging.getLogger("GCPSecrets")

# Cache for secrets to avoid repeated API calls
_secret_cache: dict = {}

def _is_running_on_gcp() -> bool:
    """
    Detect if running on GCP by checking for metadata server.
    """
    # GCE instances have this environment variable or metadata server
    return (
        os.getenv("GOOGLE_CLOUD_PROJECT") is not None or
        os.getenv("GCP_PROJECT") is not None or
        os.path.exists("/var/run/secrets/kubernetes.io")  # GKE
    )

def get_secret(secret_id: str, fallback_env_var: Optional[str] = None) -> Optional[str]:
    """
    Retrieve a secret from GCP Secret Manager with local .env fallback.
    
    Args:
        secret_id: The secret ID in GCP Secret Manager
        fallback_env_var: Optional environment variable name for local fallback
        
    Returns:
        The secret value or None if not found
    """
    # Check cache first
    if secret_id in _secret_cache:
        return _secret_cache[secret_id]
    
    # Try GCP Secret Manager if on GCP
    if _is_running_on_gcp():
        try:
            from google.cloud import secretmanager
            
            project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
            if not project_id:
                # Try to get from metadata
                import requests
                response = requests.get(
                    "http://metadata.google.internal/computeMetadata/v1/project/project-id",
                    headers={"Metadata-Flavor": "Google"},
                    timeout=2
                )
                project_id = response.text
            
            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
            
            response = client.access_secret_version(request={"name": name})
            secret_value = response.payload.data.decode("UTF-8").strip()
            
            # Cache the secret
            _secret_cache[secret_id] = secret_value
            logger.info(f"✅ Loaded secret '{secret_id}' from GCP Secret Manager")
            return secret_value
            
        except ImportError:
            logger.warning("google-cloud-secret-manager not installed. Falling back to env vars.")
        except Exception as e:
            logger.warning(f"Failed to fetch secret '{secret_id}' from GCP: {e}. Falling back to env.")
    
    # Fallback to environment variable
    env_var = fallback_env_var or secret_id
    value = os.getenv(env_var)
    
    if not value:
        # Try loading from .env.adk
        try:
            from dotenv import load_dotenv
            load_dotenv(".env.adk")
            value = os.getenv(env_var)
        except ImportError:
            pass
    
    if value:
        _secret_cache[secret_id] = value
        logger.debug(f"Loaded '{secret_id}' from environment variable")
    else:
        logger.warning(f"Secret '{secret_id}' not found in GCP or environment")
    
    return value


def get_all_trading_secrets() -> dict:
    """
    Load all required trading secrets.
    Returns a dict with all secrets for easy access.
    """
    return {
        "GOOGLE_API_KEY": get_secret("GOOGLE_API_KEY"),
        "HL_WALLET_ADDRESS": get_secret("HL_WALLET_ADDRESS"),
        "HL_PRIVATE_KEY": get_secret("HL_PRIVATE_KEY"),
        "HL_VAULT_ADDRESS": get_secret("HL_VAULT_ADDRESS"),
        "SUPABASE_URL": get_secret("SUPABASE_URL"),
        "SUPABASE_KEY": get_secret("SUPABASE_KEY"),
        "TELEGRAM_CHAT_ID": get_secret("TELEGRAM_CHAT_ID"),
    }


def clear_cache():
    """Clear the secret cache (useful for testing or rotation)."""
    global _secret_cache
    _secret_cache = {}
    logger.info("Secret cache cleared")


# Convenience functions for specific secrets
def get_google_api_key() -> Optional[str]:
    return get_secret("GOOGLE_API_KEY")

def get_hyperliquid_wallet() -> Optional[str]:
    return get_secret("HL_WALLET_ADDRESS")

def get_hyperliquid_private_key() -> Optional[str]:
    return get_secret("HL_PRIVATE_KEY")

def get_hyperliquid_vault_address() -> Optional[str]:
    """Main/vault wallet that authorized the API wallet. Used as walletAddress in CCXT."""
    return get_secret("HL_VAULT_ADDRESS")

def get_supabase_url() -> Optional[str]:
    return get_secret("SUPABASE_URL")

def get_supabase_key() -> Optional[str]:
    return get_secret("SUPABASE_KEY")
