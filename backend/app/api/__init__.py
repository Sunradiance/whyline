from flask import Blueprint
api_bp = Blueprint('api', __name__)
from . import routes  # noqa
from . import integration_routes  # noqa
from . import workspace_routes  # noqa