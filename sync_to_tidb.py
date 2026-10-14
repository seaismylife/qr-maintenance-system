import sys
import os
import urllib.parse
import certifi
import mysql.connector

def run_migration(tidb_conn_str_or_dict, render_base_url=""):
    print("=" * 60)
    print("STARTING DATA MIGRATION: LOCAL XAMPP -> TIDB CLOUD")
    print("=" * 60)

    # 1. Connect to Local MySQL (XAMPP)
    print("[1/4] Connecting to local XAMPP MySQL (127.0.0.1:3306)...")
    local_cnx = mysql.connector.connect(
        host="127.0.0.1",
        port=3306,
        user="root",
        password="",
        database="qr_maintenance_db",
    )
    local_cur = local_cnx.cursor(dictionary=True)
    print("      Connected to local database.")

    # 2. Connect to TiDB Cloud
    print("[2/4] Connecting to TiDB Cloud...")
    if isinstance(tidb_conn_str_or_dict, str):
        parsed = urllib.parse.urlsplit(tidb_conn_str_or_dict)
        tidb_kwargs = {
            "host": parsed.hostname,
            "port": parsed.port or 4000,
            "user": urllib.parse.unquote(parsed.username or ""),
            "password": urllib.parse.unquote(parsed.password or ""),
            "database": parsed.path.lstrip("/") or "test",
            "ssl_ca": certifi.where(),
            "ssl_verify_cert": True,
            "autocommit": False,
        }
    else:
        tidb_kwargs = dict(tidb_conn_str_or_dict)
        tidb_kwargs["ssl_ca"] = certifi.where()
        tidb_kwargs["ssl_verify_cert"] = True
        tidb_kwargs["autocommit"] = False

    tidb_cnx = mysql.connector.connect(**tidb_kwargs)
    tidb_cur = tidb_cnx.cursor(dictionary=True)
    print("      Connected to TiDB Cloud successfully.")

    # 3. Clean up the 5 initial demo equipment in TiDB
    print("[3/4] Removing initial demo equipment from TiDB Cloud...")
    demo_names = [
        "Desktop PC - Station 01",
        "Multimedia Projector",
        "Network Switch 24-Port",
        "Digital Multimeter",
        "Air Conditioning Unit 2.0HP"
    ]
    # Check if any demo items exist
    format_strings = ','.join(['%s'] * len(demo_names))
    tidb_cur.execute(f"DELETE FROM equipment WHERE name IN ({format_strings})", tuple(demo_names))
    deleted_demos = tidb_cur.rowcount
    tidb_cnx.commit()
    print(f"      Removed {deleted_demos} demo equipment items from TiDB.")

    # 4. Read all equipment from Local XAMPP
    print("[4/4] Migrating all local equipment to TiDB Cloud...")
    local_cur.execute("SELECT * FROM equipment WHERE (is_deleted IS NULL OR is_deleted=0) ORDER BY id ASC")
    local_equipment = local_cur.fetchall()
    print(f"      Found {len(local_equipment)} active equipment items in local XAMPP.")

    base_url = (render_base_url or "").strip().rstrip("/")
    if not base_url:
        base_url = "http://localhost:5000"

    inserted_count = 0
    updated_count = 0

    for eq in local_equipment:
        # Check if already exists in TiDB by name and location
        tidb_cur.execute(
            "SELECT id FROM equipment WHERE name=%s AND location=%s LIMIT 1",
            (eq["name"], eq["location"])
        )
        existing = tidb_cur.fetchone()

        # Generate updated QR code for Render URL
        scan_url = f"{base_url}/equipment/scan/{eq['id']}"
        qr_url = "https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=" + urllib.parse.quote(scan_url, safe="")

        if existing:
            tidb_cur.execute(
                """
                UPDATE equipment
                SET category=%s, status=%s, qr_code=%s, is_deleted=%s, deleted_at=%s
                WHERE id=%s
                """,
                (
                    eq.get("category"),
                    eq.get("status", "Working"),
                    qr_url,
                    eq.get("is_deleted", 0),
                    eq.get("deleted_at"),
                    existing["id"],
                )
            )
            updated_count += 1
        else:
            tidb_cur.execute(
                """
                INSERT INTO equipment (id, name, category, location, status, qr_code, created_at, is_deleted, deleted_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    eq["id"],
                    eq["name"],
                    eq.get("category"),
                    eq.get("location"),
                    eq.get("status", "Working"),
                    qr_url,
                    eq.get("created_at"),
                    eq.get("is_deleted", 0),
                    eq.get("deleted_at"),
                )
            )
            inserted_count += 1

    tidb_cnx.commit()
    print(f"      Migration complete: {inserted_count} new equipment inserted, {updated_count} updated.")

    # Check total count in TiDB
    tidb_cur.execute("SELECT COUNT(*) AS cnt FROM equipment WHERE (is_deleted IS NULL OR is_deleted=0)")
    final_count = tidb_cur.fetchone()["cnt"]
    print(f"      Total active equipment in TiDB Cloud now: {final_count}")

    local_cur.close()
    local_cnx.close()
    tidb_cur.close()
    tidb_cnx.close()

    print("=" * 60)
    print("SUCCESS: ALL EQUIPMENT MIGRATED TO TIDB CLOUD!")
    print("=" * 60)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python sync_to_tidb.py <TIDB_DATABASE_URL> [RENDER_BASE_URL]")
        print("Example: python sync_to_tidb.py 'mysql://user.root:pass@gateway01...:4000/test' 'https://qr-maintenance-system.onrender.com'")
        sys.exit(1)

    tidb_url = sys.argv[1]
    render_url = sys.argv[2] if len(sys.argv) > 2 else ""
    run_migration(tidb_url, render_url)
