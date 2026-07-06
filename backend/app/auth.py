import hmac
from functools import wraps
from flask import request, jsonify, session
from .config import Config


def ensure_api_key():
    """Load or generate WHYLINE_API_KEY once."""
    if Config.WHYLINE_API_KEY:
        return Config.WHYLINE_API_KEY
    import os
    key_path = os.path.join(os.path.dirname(Config.DB_PATH), '.api_key')
    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    if os.path.exists(key_path):
        with open(key_path) as f:
            key = f.read().strip()
            Config.WHYLINE_API_KEY = key
            return key
    import secrets
    key = secrets.token_urlsafe(32)
    with open(key_path, 'w') as f:
        f.write(key)
    Config.WHYLINE_API_KEY = key
    return key


from .auth_identity import is_local_client, require_workspace

# Back-compat alias — routes should use require_workspace directly.
require_session_or_key = require_workspace('read')


def require_header_secret(config_attr: str, header_name: str = 'X-Whyline-Secret', env_name: str = ''):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            expected = getattr(Config, config_attr, '') or ''
            if not expected:
                label = env_name or config_attr
                return jsonify({'error': f'{label} not configured'}), 503
            provided = request.headers.get(header_name, '')
            if not provided or not hmac.compare_digest(provided, expected):
                return jsonify({'error': 'unauthorized'}), 403
            return f(*args, **kwargs)
        return wrapped
    return decorator


require_atlassian_secret = require_header_secret('ATLASSIAN_WEBHOOK_SECRET')
require_email_secret = require_header_secret('EMAIL_WEBHOOK_SECRET')
require_linear_secret = require_header_secret('LINEAR_WEBHOOK_SECRET')
require_salesforce_secret = require_header_secret('SALESFORCE_WEBHOOK_SECRET')
require_teams_secret = require_header_secret('TEAMS_WEBHOOK_SECRET')


def require_github_webhook(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        from .services.github_verify import verify_github_signature
        if not Config.GITHUB_WEBHOOK_SECRET:
            return jsonify({'error': 'GITHUB_WEBHOOK_SECRET not configured'}), 503
        body = request.get_data()
        sig = request.headers.get('X-Hub-Signature-256', '')
        if not verify_github_signature(Config.GITHUB_WEBHOOK_SECRET, body, sig):
            return jsonify({'error': 'unauthorized'}), 403
        return f(*args, **kwargs)
    return wrapped