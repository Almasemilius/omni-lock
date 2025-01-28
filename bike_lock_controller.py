#!/usr/bin/env python3
import socket
import time
import logging
import threading
from typing import Dict
from datetime import datetime
from config import *

# Setup logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class BikeLockServer:
    # Command prefixes
    PREFIX_BYTES = bytes([0xFF, 0xFF])
    CMD_HEADER = "*CMDS"
    MANUFACTURER = "OM"
    
    def __init__(self, host, port):
        """Initialize the bike lock server.
        
        Args:
            host (str): IP address for the server to listen on
            port (int): Port number for TCP communication
        """
        self.host = host
        self.port = port
        self.server_socket = None
        self.running = False
        self.connected_locks: Dict[str, socket.socket] = {}
        self.lock_thread = None
        self.lock_info: Dict[str, dict] = {}  # Store IMEI and other info for each lock
    
    def start(self):
        """Start the TCP server to listen for lock connections."""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Allow reuse of the address
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.running = True
            
            logger.info(f"Server started on {self.host}:{self.port}")
            
            # Start accepting connections in a separate thread
            self.lock_thread = threading.Thread(target=self._accept_connections)
            self.lock_thread.daemon = True
            self.lock_thread.start()
            
            return True
        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            return False
    
    def stop(self):
        """Stop the server and close all connections."""
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        
        # Close all connected lock sockets
        for lock_id, sock in self.connected_locks.items():
            try:
                sock.close()
            except:
                pass
        self.connected_locks.clear()
        logger.info("Server stopped")
    
    def _accept_connections(self):
        """Accept incoming connections from locks."""
        while self.running:
            try:
                client_socket, address = self.server_socket.accept()
                logger.info(f"New connection from {address}")
                
                # Start a new thread to handle this connection
                client_thread = threading.Thread(
                    target=self._handle_lock_connection,
                    args=(client_socket, address)
                )
                client_thread.daemon = True
                client_thread.start()
            except Exception as e:
                if self.running:
                    logger.error(f"Error accepting connection: {e}")
    
    def _handle_lock_connection(self, client_socket: socket.socket, address):
        """Handle communication with a connected lock."""
        lock_id = None
        try:
            # Use the address as the lock identifier
            lock_id = f"lock_{address[0]}_{address[1]}"
            self.connected_locks[lock_id] = client_socket
            logger.info(f"Lock {lock_id} connected from {address}")
            
            while self.running:
                data = client_socket.recv(1024)
                if not data:
                    break
                
                # Log received data
                logger.info(f"Received from {lock_id}: {data.hex()}")
                
                self._handle_lock_message(lock_id, data)
        except Exception as e:
            logger.error(f"Error handling lock connection: {e}")
        finally:
            if lock_id and lock_id in self.connected_locks:
                del self.connected_locks[lock_id]
            try:
                client_socket.close()
            except:
                pass
            logger.info(f"Lock {lock_id} disconnected from {address}")
    
    def _handle_lock_message(self, lock_id: str, data: bytes):
        """Handle incoming messages from locks."""
        imei, cmd, params = self._parse_response(data)
        if not imei:
            return
        
        logger.info(f"Received from {lock_id} - CMD: {cmd}, Params: {params}")
        
        # Store IMEI for the lock
        self.lock_info[lock_id] = {"imei": imei}
        
        # Handle different command responses
        if cmd == "Q0":  # Check-in
            voltage = int(params[0]) if params else 0
            logger.info(f"Lock {lock_id} check-in, voltage: {voltage/100:.2f}V")
            
        elif cmd == "H0":  # Heartbeat
            status, voltage, signal = params if len(params) >= 3 else (0, 0, 0)
            logger.info(f"Lock {lock_id} heartbeat - Status: {'Unlocked' if status=='0' else 'Locked'}, "
                       f"Voltage: {int(voltage)/100:.2f}V, Signal: {signal}")
            
        elif cmd in ["L0", "L1"]:  # Lock/Unlock response
            result = "Success" if params[0] == "0" else "Failed"
            logger.info(f"Lock {lock_id} {cmd} operation: {result}")
            
        elif cmd == "S5":  # Status response
            if len(params) >= 5:
                voltage, signal, gps_sats, lock_status, _ = params
                logger.info(f"Lock {lock_id} status - Voltage: {int(voltage)/100:.2f}V, "
                          f"Signal: {signal}, GPS Satellites: {gps_sats}, "
                          f"Status: {'Unlocked' if lock_status=='0' else 'Locked'}")
    
    def _format_command(self, imei: str, cmd: str, *params) -> bytes:
        """Format command according to the protocol.
        
        Format: 0xFFFF*CMDS,OM,IMEI,TIMESTAMP,CMD,PARAMS#\n
        """
        timestamp = datetime.now().strftime("%y%m%d%H%M%S")
        params_str = ",".join(str(p) for p in params) if params else ""
        cmd_str = f"{self.CMD_HEADER},{self.MANUFACTURER},{imei},{timestamp},{cmd}"
        if params_str:
            cmd_str += f",{params_str}"
        cmd_str += "#\n"
        
        return self.PREFIX_BYTES + cmd_str.encode('ascii')
    
    def _parse_response(self, data: bytes) -> tuple:
        """Parse response from lock.
        
        Format: *CMDR,OM,IMEI,TIMESTAMP,CMD,PARAMS#
        Returns: (imei, cmd, params)
        """
        try:
            # Decode and remove trailing newline
            msg = data.decode('ascii').strip()
            if not msg.startswith("*CMDR"):
                return None, None, None
            
            # Split the message parts
            parts = msg.rstrip('#').split(',')
            if len(parts) < 5:
                return None, None, None
            
            imei = parts[2]
            cmd = parts[4]
            params = parts[5:] if len(parts) > 5 else []
            
            return imei, cmd, params
        except Exception as e:
            logger.error(f"Error parsing response: {e}")
            return None, None, None
    
    def _send_command(self, lock_id: str, command_bytes: bytes) -> bool:
        """Send a command to a specific lock."""
        if lock_id not in self.connected_locks:
            raise ValueError(f"Lock {lock_id} is not connected")
        
        try:
            sock = self.connected_locks[lock_id]
            sock.send(command_bytes)
            logger.info(f"Sent to {lock_id}: {command_bytes.hex()}")
            return True
        except Exception as e:
            logger.error(f"Error sending command to lock {lock_id}: {e}")
            return False
    
    def unlock(self, lock_id: str, reset_time: bool = True):
        """Send unlock command to a specific lock.
        
        Args:
            lock_id: ID of the lock to unlock
            reset_time: Whether to reset riding time (True) or retain it (False)
        """
        if lock_id not in self.lock_info:
            raise ValueError(f"Lock {lock_id} not recognized")
        
        imei = self.lock_info[lock_id]["imei"]
        user_id = "1234"  # Example user ID
        timestamp = str(int(time.time()))
        
        command = self._format_command(imei, "L0", "1" if not reset_time else "0", user_id, timestamp)
        return self._send_command(lock_id, command)
    
    def lock(self, lock_id: str):
        """Send lock command to a specific lock."""
        if lock_id not in self.lock_info:
            raise ValueError(f"Lock {lock_id} not recognized")
        
        imei = self.lock_info[lock_id]["imei"]
        command = self._format_command(imei, "L1")
        return self._send_command(lock_id, command)
    
    def get_status(self, lock_id: str):
        """Query the status of a specific lock."""
        if lock_id not in self.lock_info:
            raise ValueError(f"Lock {lock_id} not recognized")
        
        imei = self.lock_info[lock_id]["imei"]
        command = self._format_command(imei, "S5")
        return self._send_command(lock_id, command)

def print_commands():
    """Print available commands."""
    print("\nAvailable commands (type the command exactly as shown):")
    print("list                - List all connected locks with their status")
    print("status <lock_id>    - Get detailed lock status (voltage, signal, GPS)")
    print("unlock <lock_id>    - Unlock a bike (with ride time reset)")
    print("unlock_temp <lock_id> - Unlock a bike (preserve ride time)")
    print("lock <lock_id>      - Lock a bike")
    print("quit                - Exit the program")
    print("\nNote: lock_id will be shown when you use the 'list' command")
    print("Example: unlock lock_192.168.1.100_12345")

if __name__ == "__main__":
    server = BikeLockServer(SERVER_HOST, SERVER_PORT)
    
    try:
        if server.start():
            logger.info("Server started successfully")
            print(f"\nServer running on {SERVER_HOST}:{SERVER_PORT}")
            print_commands()
            
            while True:
                try:
                    command = input("Enter command: ").strip().split()
                    if not command:
                        continue
                    
                    cmd = command[0].lower()
                    
                    if cmd == "quit":
                        break
                    elif cmd == "list":
                        print("\nConnected locks:")
                        for lock_id in server.connected_locks:
                            info = server.lock_info.get(lock_id, {})
                            imei = info.get("imei", "Unknown IMEI")
                            print(f"- {lock_id} (IMEI: {imei})")
                    elif cmd in ["status", "lock", "unlock", "unlock_temp"]:
                        if len(command) != 2:
                            print(f"Usage: {cmd} <lock_id>")
                            continue
                            
                        lock_id = command[1]
                        
                        try:
                            if cmd == "status":
                                success = server.get_status(lock_id)
                            elif cmd == "unlock_temp":
                                success = server.unlock(lock_id, reset_time=False)
                            elif cmd == "unlock":
                                success = server.unlock(lock_id, reset_time=True)
                            else:  # lock
                                success = server.lock(lock_id)
                            
                            print(f"Command sent: {'Success' if success else 'Failed'}")
                            print("Check the logs for the lock's response")
                        except ValueError as e:
                            print(f"Error: {e}")
                    else:
                        print("Unknown command")
                        print_commands()
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    logger.error(f"Error processing command: {e}")
                    print(f"Error: {e}")
    finally:
        server.stop() 