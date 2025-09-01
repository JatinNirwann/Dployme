import subprocess
import threading
import time
import logging
from typing import Dict, Any, List, Optional
import signal
import os


class TunnelProcessManager:
    """Manages cloudflared tunnel processes"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.running_tunnels = {}  # tunnel_id -> process info
        self.tunnel_logs = {}      # tunnel_id -> log lines
        
    def start_tunnel(self, token: str, tunnel_id: str, tunnel_name: str = None) -> Dict[str, Any]:
        """Start a cloudflared tunnel process"""
        try:
            if tunnel_id in self.running_tunnels:
                return {
                    'success': False,
                    'error': f'Tunnel {tunnel_id} is already running'
                }
            
            # Prepare the cloudflared command
            command = ['cloudflared', 'tunnel', '--token', token]
            
            # Start the process
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            )
            
            # Store process info
            self.running_tunnels[tunnel_id] = {
                'process': process,
                'token': token,
                'name': tunnel_name or tunnel_id,
                'start_time': time.time(),
                'command': ' '.join(command)
            }
            
            # Initialize logs
            self.tunnel_logs[tunnel_id] = []
            
            # Start log capture thread
            log_thread = threading.Thread(
                target=self._capture_logs,
                args=(tunnel_id, process),
                daemon=True
            )
            log_thread.start()
            
            self.logger.info(f'Started tunnel {tunnel_id} with PID {process.pid}')
            
            return {
                'success': True,
                'tunnel_id': tunnel_id,
                'pid': process.pid,
                'message': f'Tunnel {tunnel_id} started successfully'
            }
            
        except FileNotFoundError:
            return {
                'success': False,
                'error': 'cloudflared not found. Please install cloudflared first.'
            }
        except Exception as e:
            self.logger.error(f'Error starting tunnel {tunnel_id}: {e}')
            return {
                'success': False,
                'error': str(e)
            }
    
    def stop_tunnel(self, tunnel_id: str) -> Dict[str, Any]:
        """Stop a specific tunnel"""
        try:
            if tunnel_id not in self.running_tunnels:
                return {
                    'success': False,
                    'error': f'Tunnel {tunnel_id} is not running'
                }
            
            tunnel_info = self.running_tunnels[tunnel_id]
            process = tunnel_info['process']
            
            # Terminate the process
            if os.name == 'nt':  # Windows
                process.terminate()
            else:  # Unix/Linux
                process.terminate()
            
            # Wait for process to end
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            
            # Clean up
            del self.running_tunnels[tunnel_id]
            
            self.logger.info(f'Stopped tunnel {tunnel_id}')
            
            return {
                'success': True,
                'message': f'Tunnel {tunnel_id} stopped successfully'
            }
            
        except Exception as e:
            self.logger.error(f'Error stopping tunnel {tunnel_id}: {e}')
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_tunnel_status(self, tunnel_id: str) -> Dict[str, Any]:
        """Get status of a specific tunnel"""
        if tunnel_id not in self.running_tunnels:
            return {
                'running': False,
                'status': 'stopped'
            }
        
        tunnel_info = self.running_tunnels[tunnel_id]
        process = tunnel_info['process']
        
        # Check if process is still running
        if process.poll() is None:
            uptime = int(time.time() - tunnel_info['start_time'])
            return {
                'running': True,
                'status': 'running',
                'pid': process.pid,
                'uptime': uptime,
                'name': tunnel_info['name'],
                'command': tunnel_info['command']
            }
        else:
            # Process has ended, clean up
            del self.running_tunnels[tunnel_id]
            return {
                'running': False,
                'status': 'stopped',
                'exit_code': process.returncode
            }
    
    def get_tunnel_logs(self, tunnel_id: str, lines: int = 100) -> List[str]:
        """Get recent log lines for a tunnel"""
        if tunnel_id not in self.tunnel_logs:
            return []
        
        logs = self.tunnel_logs[tunnel_id]
        return logs[-lines:] if lines > 0 else logs
    
    def list_running_tunnels(self) -> List[Dict[str, Any]]:
        """List all running tunnels"""
        running = []
        
        # Clean up dead processes first
        dead_tunnels = []
        for tunnel_id, tunnel_info in self.running_tunnels.items():
            if tunnel_info['process'].poll() is not None:
                dead_tunnels.append(tunnel_id)
        
        for tunnel_id in dead_tunnels:
            del self.running_tunnels[tunnel_id]
        
        # Return info for running tunnels
        for tunnel_id, tunnel_info in self.running_tunnels.items():
            uptime = int(time.time() - tunnel_info['start_time'])
            running.append({
                'tunnel_id': tunnel_id,
                'name': tunnel_info['name'],
                'pid': tunnel_info['process'].pid,
                'uptime': uptime,
                'status': 'running'
            })
        
        return running
    
    def stop_all_tunnels(self) -> Dict[str, Any]:
        """Stop all running tunnels"""
        results = []
        tunnel_ids = list(self.running_tunnels.keys())
        
        for tunnel_id in tunnel_ids:
            result = self.stop_tunnel(tunnel_id)
            results.append({
                'tunnel_id': tunnel_id,
                'success': result['success'],
                'message': result.get('message', result.get('error', ''))
            })
        
        return {
            'success': True,
            'stopped_count': len(results),
            'results': results
        }
    
    def _capture_logs(self, tunnel_id: str, process: subprocess.Popen):
        """Capture logs from a tunnel process"""
        try:
            for line in iter(process.stdout.readline, ''):
                if line:
                    log_entry = f"[{time.strftime('%H:%M:%S')}] {line.strip()}"
                    
                    if tunnel_id not in self.tunnel_logs:
                        self.tunnel_logs[tunnel_id] = []
                    
                    self.tunnel_logs[tunnel_id].append(log_entry)
                    
                    # Keep only last 1000 lines to prevent memory issues
                    if len(self.tunnel_logs[tunnel_id]) > 1000:
                        self.tunnel_logs[tunnel_id] = self.tunnel_logs[tunnel_id][-1000:]
                
                # If process has ended, break
                if process.poll() is not None:
                    break
                    
        except Exception as e:
            self.logger.error(f'Error capturing logs for tunnel {tunnel_id}: {e}')
        finally:
            # Ensure we clean up when the process ends
            if tunnel_id in self.running_tunnels:
                process_info = self.running_tunnels[tunnel_id]['process']
                if process_info.poll() is not None:
                    # Process has ended, we'll clean this up in the next status check
                    pass
