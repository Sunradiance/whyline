import os
from flask import Flask, abort, send_from_directory
from .config import Config
from .auth import ensure_api_key
from .store import store


def create_app(config_class=Config):
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
    public = os.path.join(root, 'public')

    app = Flask(__name__, static_folder=None)
    app.config.from_object(config_class)
    app.secret_key = Config.SECRET_KEY
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_HTTPONLY'] = True

    if hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False

    ensure_api_key()
    store._run_migrations()
    store.seed_if_empty()
    from .services.capture_queue import drain_pending
    drain_pending()

    from .api import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    ALLOWED_STATIC = {'css', 'js', 'integrations'}

    @app.route('/')
    def index():
        return send_from_directory(public, 'index.html')

    @app.route('/<path:filepath>')
    def static_files(filepath):
        # Block path traversal and sensitive paths
        if '..' in filepath or filepath.startswith('.'):
            abort(404)
        parts = filepath.split('/')
        if parts[0] not in ALLOWED_STATIC and not filepath.endswith('.md'):
            abort(404)
        directory = public
        if parts[0] == 'integrations':
            directory = root
        full = os.path.join(directory, filepath)
        if not os.path.isfile(full):
            abort(404)
        return send_from_directory(directory, filepath)

    return app