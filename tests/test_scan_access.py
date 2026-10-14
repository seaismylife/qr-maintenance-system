from app import app as flask_app

def test_scan_camera_is_available_for_faculty():
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = {
                "id": "9",
                "name": "Faculty User",
                "email": "faculty@example.com",
                "role": "faculty",
            }
            session["last_activity"] = "9999999999"

        response = client.get("/scan")
    assert response.status_code == 200

def test_scan_camera_is_available_for_technician():
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = {
                "id": "4",
                "name": "Technician User",
                "email": "technician@example.com",
                "role": "technician",
            }
            session["last_activity"] = "9999999999"

        response = client.get("/scan")
    assert response.status_code == 200

def test_scan_camera_is_available_for_custodian():
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = {
                "id": "2",
                "name": "Custodian User",
                "email": "custodian@example.com",
                "role": "custodian",
            }
            session["last_activity"] = "9999999999"

        response = client.get("/scan")
    assert response.status_code == 200

def test_scan_camera_requires_login():
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as client:
        response = client.get("/scan")
    assert response.status_code == 302

def test_admin_scan_and_qr_print_back_links():
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = {
                "id": "1",
                "name": "Admin User",
                "email": "admin@example.com",
                "role": "admin",
            }
            session["last_activity"] = "9999999999"

        res_scan = client.get("/scan")
        assert res_scan.status_code == 200
        assert b"Back" in res_scan.data

        res_print = client.get("/qr/print")
        assert res_print.status_code == 200
        assert b"/dashboard/admin" in res_print.data
        assert b"/dashboard/custodian" not in res_print.data

        res_cust = client.get("/dashboard/custodian")
        assert res_cust.status_code == 302
        assert "/dashboard/admin" in res_cust.headers["Location"]

