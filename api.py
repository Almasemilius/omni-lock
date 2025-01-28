from flask import Flask, jsonify, request
from bike_lock_controller import BikeLockServer
from config import *
import threading

app = Flask(__name__)

# Global server instance
lock_server = None

def start_server():
    global lock_server
    lock_server = BikeLockServer(SERVER_HOST, SERVER_PORT)
    lock_server.start()

@app.route('/api/locks', methods=['GET'])
def get_locks():
    """Get list of all connected locks."""
    if not lock_server:
        return jsonify({"error": "Server not running"}), 500
    
    locks = []
    for lock_id in lock_server.connected_locks:
        info = lock_server.lock_info.get(lock_id, {})
        locks.append({
            "id": lock_id,
            "imei": info.get("imei", "Unknown"),
            "connected": True
        })
    
    return jsonify({"locks": locks})

@app.route('/api/locks/<lock_id>/status', methods=['GET'])
def get_lock_status(lock_id):
    """Get status of a specific lock."""
    if not lock_server:
        return jsonify({"error": "Server not running"}), 500
    
    try:
        success = lock_server.get_status(lock_id)
        if success:
            return jsonify({"status": "command_sent"})
        return jsonify({"error": "Failed to send command"}), 500
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

@app.route('/api/locks/<lock_id>/unlock', methods=['POST'])
def unlock_lock(lock_id):
    """Unlock a specific lock."""
    if not lock_server:
        return jsonify({"error": "Server not running"}), 500
    
    try:
        # Get reset_time from request data, default to True
        data = request.get_json(silent=True) or {}
        reset_time = data.get('reset_time', True)
        
        success = lock_server.unlock(lock_id, reset_time=reset_time)
        if success:
            return jsonify({"status": "command_sent"})
        return jsonify({"error": "Failed to send command"}), 500
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

@app.route('/api/locks/<lock_id>/lock', methods=['POST'])
def lock_lock(lock_id):
    """Lock a specific lock."""
    if not lock_server:
        return jsonify({"error": "Server not running"}), 500
    
    try:
        success = lock_server.lock(lock_id)
        if success:
            return jsonify({"status": "command_sent"})
        return jsonify({"error": "Failed to send command"}), 500
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

if __name__ == '__main__':
    # Start the lock server in a separate thread
    server_thread = threading.Thread(target=start_server)
    server_thread.daemon = True
    server_thread.start()
    
    # Start the Flask API
    app.run(host='0.0.0.0', port=5000) 