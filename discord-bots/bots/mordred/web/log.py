import os
from datetime import datetime, timedelta
from functools import wraps
from flask import session,request,jsonify,redirect,url_for,current_app

LAST_CLEANUP_DAY = "2000-02-29" #千禧年:)
CLEANUP_HOUR_UTC = 4 

def audit_logs(action:str): # 敏感操作logs
    try:
        token = session.get('token','UNKNOWN_TOKEN')
        timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        admin_log_file = current_app.config.get('ADMIN_LOG_FILE','admin.txt')
        log_message = f"[{timestamp}][Action:{action}][Token:{token}]\n"
        with open(admin_log_file,'a') as f:
            f.write(log_message)
    except Exception as e:
        current_app.logger.error(f"Failed to write to admin audit log:{e}")

def run_daily_cleanup_if_needed():
    """
    检查是否需要运行每日清理任务。
    仅在每天指定的小时过后，且当天尚未清理时，才会执行。
    """
    global LAST_CLEANUP_DAY
    
    current_time = datetime.utcnow()
    today_str = current_time.strftime('%Y-%m-%d')

    if today_str > LAST_CLEANUP_DAY and current_time.hour >= CLEANUP_HOUR_UTC:
        
        current_app.logger.info(f"Triggering daily log cleanup for {today_str}.")
        try:
            cutoff_date = current_time - timedelta(days=7)
            log_dir = current_app.config.get('LOG_DIR', 'LOGS')
            
            if not os.path.isdir(log_dir):
                current_app.logger.warning(f"Log cleanup skipped: Directory '{log_dir}' not found.")
                LAST_CLEANUP_DAY = today_str
                return

            for filename in os.listdir(log_dir):
                if filename.endswith(".txt"):
                    try:
                        file_path = os.path.join(log_dir, filename)
                        file_date_str = os.path.splitext(filename)[0]
                        file_date = datetime.strptime(file_date_str, '%Y-%m-%d')
                        
                        if file_date < cutoff_date:
                            os.remove(file_path)
                            audit_logs(f"Auto-cleaned old log file: {filename}")
                    except (ValueError, IndexError):
                        current_app.logger.debug(f"Log cleanup skipped invalid filename: {filename}")
                        continue
            
            LAST_CLEANUP_DAY = today_str
            current_app.logger.info(f"Daily log cleanup for {today_str} completed.")

        except Exception as e:
            current_app.logger.error(f"An error occurred during log cleanup: {e}")
    
def login_required(f):
    @wraps(f)
    def decorated_function(*args,**kwargs):
        if 'logged_in' not in session:
            if request.path.startswith('/api/'):
                return jsonify({"status":"error","message":"Authentication required"}),401
            return redirect(url_for('config_page'))
        return f(*args,**kwargs)
    return decorated_function