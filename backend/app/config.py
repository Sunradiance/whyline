import os
import secrets
from dotenv import load_dotenv

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
env_path = os.path.join(project_root, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path, override=True)
else:
    load_dotenv(override=True)


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    JSON_AS_ASCII = False

    # Security: localhost only by default — never expose .env on LAN
    HOST = os.environ.get('WHYLINE_HOST', '127.0.0.1')
    PORT = int(os.environ.get('WHYLINE_PORT', '8793'))

    # Required for AI + mutation endpoints (generated on first run if missing)
    WHYLINE_API_KEY = os.environ.get('WHYLINE_API_KEY', '')

    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.groq.com/openai/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'qwen/qwen3-32b')

    DB_PATH = os.environ.get('WHYLINE_DB_PATH', os.path.join(project_root, 'data', 'whyline.db'))

    SOL_DONATION_ADDRESS = os.environ.get('SOL_DONATION_ADDRESS', '')

    # Comma-separated markers that trigger webhook extraction (e.g. [decision],#decision)
    _markers = os.environ.get('WEBHOOK_DECISION_MARKERS', '')
    WEBHOOK_DECISION_MARKERS = tuple(m.strip().lower() for m in _markers.split(',') if m.strip()) or None

    NEAR_DUP_SCORE_THRESHOLD = float(os.environ.get('NEAR_DUP_SCORE_THRESHOLD', '4.0'))

    SLACK_SIGNING_SECRET = os.environ.get('SLACK_SIGNING_SECRET', '')
    SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN', '')
    ATLASSIAN_WEBHOOK_SECRET = os.environ.get('ATLASSIAN_WEBHOOK_SECRET', '')
    EMAIL_WEBHOOK_SECRET = os.environ.get('EMAIL_WEBHOOK_SECRET', '')
    GITHUB_WEBHOOK_SECRET = os.environ.get('GITHUB_WEBHOOK_SECRET', '')
    LINEAR_WEBHOOK_SECRET = os.environ.get('LINEAR_WEBHOOK_SECRET', '')
    SALESFORCE_WEBHOOK_SECRET = os.environ.get('SALESFORCE_WEBHOOK_SECRET', '')
    TEAMS_WEBHOOK_SECRET = os.environ.get('TEAMS_WEBHOOK_SECRET', '')

    RETRIEVAL_TOP_K = int(os.environ.get('RETRIEVAL_TOP_K', '8'))
    SLACK_CAPTURE_REACTIONS = {'pushpin', 'whyline', 'pinning_board'}

    CAPTURE_MAX_RETRIES = int(os.environ.get('CAPTURE_MAX_RETRIES', '3'))
    CAPTURE_MAX_CONCURRENT = int(os.environ.get('CAPTURE_MAX_CONCURRENT', '4'))
    CAPTURE_PRUNE_DAYS = int(os.environ.get('CAPTURE_PRUNE_DAYS', '7'))
    CAPTURE_PRUNE_EVERY_N = int(os.environ.get('CAPTURE_PRUNE_EVERY_N', '50'))
    CAPTURE_RETRY_BASE_SECONDS = float(os.environ.get('CAPTURE_RETRY_BASE_SECONDS', '2'))
    CAPTURE_RETRY_MAX_SECONDS = float(os.environ.get('CAPTURE_RETRY_MAX_SECONDS', '60'))

    AUTH_MODE = os.environ.get('WHYLINE_AUTH_MODE', 'solo')  # solo | team | open
    ALLOW_SOLO_DOWNGRADE = os.environ.get('WHYLINE_ALLOW_SOLO_DOWNGRADE', '').strip().lower() in (
        '1',
        'true',
        'yes',
    )
    AUTH_RATE_LIMIT = int(os.environ.get('WHYLINE_AUTH_RATE_LIMIT', '20'))

    @classmethod
    def status(cls) -> dict:
        return {
            'llm': bool(cls.LLM_API_KEY),
            'ready': bool(cls.LLM_API_KEY),
            'model': cls.LLM_MODEL_NAME if cls.LLM_API_KEY else None,
            'slack': bool(cls.SLACK_BOT_TOKEN and cls.SLACK_SIGNING_SECRET),
            'atlassian': bool(cls.ATLASSIAN_WEBHOOK_SECRET),
            'email': bool(cls.EMAIL_WEBHOOK_SECRET),
            'github': bool(cls.GITHUB_WEBHOOK_SECRET),
            'linear': bool(cls.LINEAR_WEBHOOK_SECRET),
            'salesforce': bool(cls.SALESFORCE_WEBHOOK_SECRET),
            'teams': bool(cls.TEAMS_WEBHOOK_SECRET),
            'mcp': True,
            'db': cls.DB_PATH,
        }

    @classmethod
    def validate(cls) -> list[str]:
        w = []
        if not cls.LLM_API_KEY:
            w.append('LLM_API_KEY not set — AI disabled')
        if not cls.WHYLINE_API_KEY:
            w.append('WHYLINE_API_KEY not set — will auto-generate on first boot (check data/.api_key)')
        if not cls.SLACK_SIGNING_SECRET and cls.SLACK_BOT_TOKEN:
            w.append('SLACK_BOT_TOKEN set but SLACK_SIGNING_SECRET missing — Slack events rejected')
        return w