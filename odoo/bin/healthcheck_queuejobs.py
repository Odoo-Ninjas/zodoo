import psycopg2
import os
import datetime

def check_queue_job_status(db_config):
    """
    Checks if there are any pending jobs and no running jobs in the queue_job table.
    """
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    query_pending = "SELECT COUNT(*) FROM queue_job WHERE state in ('pending', 'enqueued') and (eta is null or eta < '{now}');"
    query_running = "SELECT COUNT(*) FROM queue_job WHERE state = 'started';"

    try:
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()

        cursor.execute(query_pending)
        pending_count = cursor.fetchone()[0]

        cursor.execute(query_running)
        running_count = cursor.fetchone()[0]

        if pending_count > 0 and running_count == 0:
            raise Exception("Pending jobs detected with no running jobs.")
        else:
            print(f"ℹ️ Pending: {pending_count}, Running: {running_count}")
            return False

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# Example usage:
if __name__ == "__main__":
    db_config = {
        "host": os.getenv("DB_HOST"),
        "port": int(os.getenv("DB_PORT")),
        "dbname": os.getenv("DBNAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PWD"),
    }
    check_queue_job_status(db_config)