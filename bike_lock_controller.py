#!/usr/bin/env python3
import socket
import time
import logging
import struct
import datetime
import threading
from typing import Dict
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
    def __init__(self, host, port, secret_key):
        """Initialize the bike lock server.
        
        Args:
            host (str): IP address for the server to listen on
            port (int): Port number for TCP communication
            secret_key (str): Secret key for secure communication
        """
        self.host = host
        self.port = port
        self.secret_key = secret_key
        self.server_socket = None
        self.running = False
        self.connected_locks: Dict[str, socket.socket] = {}
        self.lock_thread = None
    
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
        """Handle communication with a connected lock.
        
        Args:
            client_socket: Socket connection to the lock
            address: Address of the connected lock
        """
        lock_id = None
        try:
            # First message should be the lock's identification
            data = client_socket.recv(1024)
            if data:
                # TODO: Implement proper parsing of lock identification message
                lock_id = data.decode('utf-8').strip()
                self.connected_locks[lock_id] = client_socket
                logger.info(f"Lock {lock_id} registered from {address}")
            
            while self.running:
                data = client_socket.recv(1024)
                if not data:
                    break
                
                # Handle incoming messages from the lock
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
    
    def _handle_lock_message(self, lock_id: str, message: bytes):
        """Handle incoming messages from locks.
        
        Args:
            lock_id: ID of the lock sending the message
            message: Message received from the lock
        """
        try:
            # TODO: Implement proper message parsing and handling
            logger.info(f"Received message from lock {lock_id}: {message}")
        except Exception as e:
            logger.error(f"Error handling message from lock {lock_id}: {e}")
    
    def _send_command(self, lock_id: str, command_bytes: bytes) -> bytes:
        """Send a command to a specific lock.
        
        Args:
            lock_id: ID of the lock to send command to
            command_bytes: The formatted command to send
            
        Returns:
            bytes: Response from the lock
        """
        if lock_id not in self.connected_locks:
            raise ValueError(f"Lock {lock_id} is not connected")
        
        try:
            sock = self.connected_locks[lock_id]
            sock.send(command_bytes)
            response = sock.recv(1024)
            return response
        except Exception as e:
            logger.error(f"Error sending command to lock {lock_id}: {e}")
            raise
    
    def unlock(self, lock_id: str, user_id: str, retain_riding_time=True):
        """Send unlock command to a specific lock.
        
        Args:
            lock_id: ID of the lock to unlock
            user_id: ID of the user unlocking the bike
            retain_riding_time: Whether to retain previous riding time
            
        Returns:
            tuple: (success: bool, message: str)
        """
        command = self._format_command(
            "L0",
            user_id,
            retain_time=retain_riding_time
        )
        response = self._send_command(lock_id, command)
        return self._parse_response(response)
    
    def lock(self, lock_id: str, user_id: str, ride_duration=None):
        """Send lock command to a specific lock.
        
        Args:
            lock_id: ID of the lock to lock
            user_id: ID of the user locking the bike
            ride_duration: Duration of the ride in seconds
            
        Returns:
            tuple: (success: bool, message: str)
        """
        command = self._format_command(
            "L1",
            user_id,
            ride_duration=ride_duration
        )
        response = self._send_command(lock_id, command)
        return self._parse_response(response)
    
    def get_status(self, lock_id: str, user_id: str):
        """Query the status of a specific lock.
        
        Args:
            lock_id: ID of the lock to query
            user_id: ID of the user querying the status
            
        Returns:
            tuple: (success: bool, message: str)
        """
        command = self._format_command(
            "S5",
            user_id
        )
        response = self._send_command(lock_id, command)
        return self._parse_response(response)
    
    def _format_command(self, cmd_type, user_id, **kwargs):
        """Format command according to the protocol."""
        timestamp = int(time.time())
        
        # Basic command structure
        command = {
            "cmd": cmd_type,
            "user_id": user_id,
            "timestamp": timestamp
        }
        
        # Add command-specific parameters
        command.update(kwargs)
        
        # TODO: Implement proper command formatting and encryption using secret_key
        command_str = f"{command['cmd']}|{command['user_id']}|{command['timestamp']}"
        return command_str.encode('utf-8')
    
    def _parse_response(self, response):
        """Parse the response from the lock."""
        try:
            # TODO: Implement proper response parsing according to the protocol
            response_code = int(response.decode('utf-8').split('|')[0])
            return response_code == 0, "Success" if response_code == 0 else "Failed"
        except Exception as e:
            logger.error(f"Error parsing response: {e}")
            return False, "Failed to parse response"

def print_commands():
    """Print available commands."""
    print("\nAvailable commands (type the command exactly as shown):")
    print("list                     - List all connected locks")
    print("status <lock_id> <user_id>  - Get lock status (e.g., status LOCK001 USER123)")
    print("unlock <lock_id> <user_id>  - Unlock a bike (e.g., unlock LOCK001 USER123)")
    print("lock <lock_id> <user_id>    - Lock a bike (e.g., lock LOCK001 USER123)")
    print("quit                     - Exit the program")
    print("\nNote: Don't use the numbers, type the actual command name!")
    print("Example: Type 'unlock LOCK001 USER123' to unlock bike LOCK001")

if __name__ == "__main__":
    server = BikeLockServer(SERVER_HOST, SERVER_PORT, SECRET_KEY)
    
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
                            print(f"- {lock_id}")
                    elif cmd in ["status", "lock", "unlock"]:
                        if len(command) != 3:
                            print(f"Usage: {cmd} <lock_id> <user_id>")
                            continue
                            
                        lock_id = command[1]
                        user_id = command[2]
                        
                        try:
                            if cmd == "status":
                                success, message = server.get_status(lock_id, user_id)
                            elif cmd == "unlock":
                                success, message = server.unlock(lock_id, user_id)
                            else:  # lock
                                success, message = server.lock(lock_id, user_id)
                            
                            print(f"Result: {message}")
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