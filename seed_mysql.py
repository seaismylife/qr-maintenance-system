import bcrypt
from models import get_db, now_utc

DEFAULT_USERS = [
    ("Administrator", "admin@school.edu", "admin", "admin123"),
    ("Custodian", "custodian@school.edu", "custodian", "custodian123"),
    ("Technician", "technician@school.edu", "technician", "technician123"),
    ("Faculty", "faculty@school.edu", "faculty", "faculty123"),
]

DEFAULT_EQUIPMENT = [
    ("Desktop PC - Station 01", "Computers", "Laboratory 1", "Working"),
    ("Multimedia Projector", "Audio/Visual", "Laboratory 2", "Working"),
    ("Network Switch 24-Port", "Networking", "Laboratory 3", "Working"),
    ("Digital Multimeter", "Testing Equipment", "Laboratory 4", "Working"),
    ("Air Conditioning Unit 2.0HP", "Facilities", "Laboratory 1", "Working"),
]

def main():
    import urllib.parse
    import config

    db = get_db()
    cur = db.cursor(dictionary=True)

    for name, email, role, password in DEFAULT_USERS:
        cur.execute("SELECT id FROM users WHERE email=%s LIMIT 1", (email,))
        existing = cur.fetchone()
        if existing:
            cur.execute("UPDATE users SET name=%s, role=%s WHERE id=%s", (name, role, existing["id"]))
            continue
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        cur.execute(
            "INSERT INTO users (name, email, password, role, created_at) VALUES (%s, %s, %s, %s, %s)",
            (name, email, hashed, role, now_utc().replace(tzinfo=None)),
        )

    cur.execute("SELECT COUNT(*) AS cnt FROM equipment WHERE is_deleted=0")
    if cur.fetchone()["cnt"] == 0:
        base_url = config.PUBLIC_BASE_URL if config.PUBLIC_BASE_URL else "http://localhost:5000"
        for eq_name, category, location, status in DEFAULT_EQUIPMENT:
            cur.execute(
                "INSERT INTO equipment (name, category, location, status, qr_code, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (eq_name, category, location, status, "", now_utc().replace(tzinfo=None)),
            )
            eq_id = cur.lastrowid
            scan_url = f"{base_url}/equipment/scan/{eq_id}"
            qr_url = "https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=" + urllib.parse.quote(scan_url, safe="")
            cur.execute("UPDATE equipment SET qr_code=%s WHERE id=%s", (qr_url, eq_id))

    db.commit()
    cur.close()
    db.close()

if __name__ == "__main__":
    main()

