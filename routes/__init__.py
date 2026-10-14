from routes.auth       import auth_bp
from routes.dashboard  import dashboard_bp
from routes.equipment  import equipment_bp
from routes.requests   import requests_bp
from routes.reports    import reports_bp
from routes.user_mgmt  import user_mgmt_bp
from routes.submit     import submit_bp
from routes.my_req     import my_req_bp
from routes.qr         import qr_bp
from routes.scan       import scan_bp
from routes.logbook    import logbook_bp
from routes.notifications import notifications_bp

__all__ = [
    "auth_bp","dashboard_bp","equipment_bp","requests_bp",
    "reports_bp","user_mgmt_bp","submit_bp","my_req_bp","qr_bp","scan_bp","logbook_bp",    "notifications_bp"
]

