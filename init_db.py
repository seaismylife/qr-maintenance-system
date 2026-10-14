import sys
import time
from models import get_db
import seed_mysql

def reset_data():
    db = get_db()
    cur = db.cursor()
    cur.execute("SET FOREIGN_KEY_CHECKS = 0")
    for table in ["maintenance_logs", "maintenance_requests", "activity_logs", "notifications", "equipment", "users"]:
        cur.execute(f"TRUNCATE TABLE `{table}`")
    cur.execute("SET FOREIGN_KEY_CHECKS = 1")
    db.commit()
    cur.close()
    db.close()
    seed_mysql.main()

def initialize(seed: bool = False, reset: bool = False, max_retries: int = 5, retry_delay: int = 3):
    if reset:
        print("[init_db] Resetting and seeding database tables...")
        reset_data()
        print("[init_db] Reset and seed complete.")
        return

    cnx = None
    for attempt in range(1, max_retries + 1):
        try:
            print(f"[init_db] Connecting to database (attempt {attempt}/{max_retries})...")
            cnx = get_db()
            print("[init_db] Database connected and schema verified.")
            break
        except Exception as e:
            print(f"[init_db] Database connection attempt {attempt} failed: {e}")
            if attempt == max_retries:
                raise
            time.sleep(retry_delay)

    if cnx:
        cnx.close()

    if seed:
        print("[init_db] Running database seed...")
        seed_mysql.main()
        print("[init_db] Seed completed successfully.")

if __name__ == "__main__":
    should_reset = "--reset" in sys.argv or "--clean-data" in sys.argv
    should_seed = "--seed" in sys.argv or should_reset
    try:
        initialize(seed=should_seed, reset=should_reset)
        print("[init_db] Database initialization succeeded.")
    except Exception as e:
        print(f"[init_db] Database initialization error: {e}", file=sys.stderr)
        sys.exit(1)

