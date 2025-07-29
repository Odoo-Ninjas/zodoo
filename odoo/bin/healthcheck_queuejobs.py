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

    QUEUEJOBS_MAX_AGE_BEFORE_RESTART = 60 * int(os.getenv("QUEUEJOBS_MAX_AGE_BEFORE_RESTART_MINUTES", "120"))

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

        cursor.execute("SELECT MIN(date_started) FROM queue_job WHERE state = 'started';")
        started = cursor.fetchone()
        if started:
            started = started[0]
            if (datetime.datetime.now() - started).total_seconds() > QUEUEJOBS_MAX_AGE_BEFORE_RESTART:
                raise Exception(f"Queue jobs have been running for longer than QUEUEJOBS_MAX_AGE_BEFORE_RESTART_MINUTES= {QUEUEJOBS_MAX_AGE_BEFORE_RESTART}seconds, consider restarting the service.")

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