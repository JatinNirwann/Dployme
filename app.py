import os
import json
import logging
from flask import Flask, render_template, request, jsonify, flash, redirect, url_for
from flask import session
import socket
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
sys.path.append(str(Path(__file__).parent / 'app'))

from cloudflare_tunnel_api import TunnelManager, CloudflareTunnelAPI
from cloudflare_config import CloudflareConfig
from tunnel_process_manager import TunnelProcessManager

app = Flask(__name__, template_folder='.')
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

tunnel_manager = TunnelProcessManager()


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "192.168.1.100"


def load_config():
    try:
        config = CloudflareConfig.from_env()
        if not config.validate():
            return None
        return config
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return None


def get_tunnel_manager():
    config = load_config()
    if not config:
        return None
    return TunnelManager(config.api_token, config.zone_id, config.account_id)


@app.route('/')
def index():
    config = load_config()
    local_ip = get_local_ip()
    
    config_status = {
        'configured': config is not None,
        'api_token': bool(config.api_token if config else False),
        'zone_id': bool(config.zone_id if config else False),
        'account_id': bool(config.account_id if config else False)
    }
    
    return render_template('tunnel_dashboard.html', 
                         config_status=config_status, 
                         local_ip=local_ip)


@app.route('/api/config', methods=['GET'])
def get_config_status():
    config = load_config()
    local_ip = get_local_ip()
    
    if config:
        try:
            manager = get_tunnel_manager()
            api = CloudflareTunnelAPI(config.api_token, config.zone_id, config.account_id)
            valid = api.verify_credentials()
            zone_name = api._get_zone_name() if valid else None
        except Exception as e:
            valid = False
            zone_name = None
            logger.error(f"Config validation error: {e}")
    else:
        valid = False
        zone_name = None
    
    return jsonify({
        'configured': config is not None,
        'valid': valid,
        'zone_name': zone_name,
        'local_ip': local_ip,
        'has_api_token': bool(config.api_token if config else False),
        'has_zone_id': bool(config.zone_id if config else False),
        'has_account_id': bool(config.account_id if config else False)
    })


@app.route('/api/tunnels', methods=['GET'])
def list_tunnels():
    manager = get_tunnel_manager()
    if not manager:
        return jsonify({'error': 'Configuration not available'}), 400
    
    try:
        api = CloudflareTunnelAPI(load_config().api_token, load_config().zone_id, load_config().account_id)
        tunnels = api.list_tunnels()
        return jsonify({'tunnels': tunnels})
    except Exception as e:
        logger.error(f"Error listing tunnels: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tunnels', methods=['POST'])
def create_tunnel():
    manager = get_tunnel_manager()
    if not manager:
        return jsonify({'error': 'Configuration not available'}), 400
    
    data = request.get_json()
    subdomain = data.get('subdomain')
    port = data.get('port')
    use_local_ip = data.get('use_local_ip', True)
    auto_start = data.get('auto_start', True)
    
    if not subdomain or not port:
        return jsonify({'error': 'Subdomain and port are required'}), 400
    
    try:
        if use_local_ip:
            local_ip = get_local_ip()
            service_url = f'http://{local_ip}:{port}'
        else:
            service_url = f'http://localhost:{port}'
        
        config = load_config()
        api = CloudflareTunnelAPI(config.api_token, config.zone_id, config.account_id)
        
        tunnel_info = api.create_tunnel(f'{subdomain}-tunnel')
        tunnel_id = tunnel_info['id']
        
        zone_name = api._get_zone_name()
        hostname = f'{subdomain}.{zone_name}'
        
        route_data = {
            'config': {
                'ingress': [
                    {
                        'hostname': hostname,
                        'service': service_url
                    },
                    {
                        'service': 'http_status:404'
                    }
                ]
            }
        }
        
        route_url = f'{api.base_url}/accounts/{api.account_id}/cfd_tunnel/{tunnel_id}/configurations'
        import requests
        route_response = requests.put(route_url, json=route_data, headers=api.headers)
        route_response.raise_for_status()
        
        dns_info = api.create_dns_record(subdomain, tunnel_id)
        
        result = {
            'tunnel': tunnel_info,
            'dns': dns_info,
            'subdomain': hostname,
            'service_url': service_url,
            'cloudflared_command': f'cloudflared tunnel --token {tunnel_info.get("token", "TOKEN_NOT_AVAILABLE")}',
            'setup_complete': True,
            'auto_started': False
        }
        
        if auto_start and tunnel_info.get('token'):
            start_result = tunnel_manager.start_tunnel(
                tunnel_info['token'], 
                tunnel_id, 
                f'{subdomain}-tunnel'
            )
            result['auto_started'] = start_result['success']
            result['start_result'] = start_result
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error creating tunnel: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tunnels/<tunnel_id>', methods=['DELETE'])
def delete_tunnel(tunnel_id):
    manager = get_tunnel_manager()
    if not manager:
        return jsonify({'error': 'Configuration not available'}), 400
    
    try:
        config = load_config()
        api = CloudflareTunnelAPI(config.api_token, config.zone_id, config.account_id)
        success = api.delete_tunnel(tunnel_id)
        
        if success:
            return jsonify({'message': 'Tunnel deleted successfully'})
        else:
            return jsonify({'error': 'Failed to delete tunnel'}), 500
            
    except Exception as e:
        logger.error(f"Error deleting tunnel: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tunnels/cleanup', methods=['POST'])
def cleanup_subdomain():
    manager = get_tunnel_manager()
    if not manager:
        return jsonify({'error': 'Configuration not available'}), 400
    
    data = request.get_json()
    subdomain = data.get('subdomain')
    
    if not subdomain:
        return jsonify({'error': 'Subdomain is required'}), 400
    
    try:
        success = manager.cleanup(subdomain)
        
        if success:
            return jsonify({'message': f'Cleaned up subdomain: {subdomain}'})
        else:
            return jsonify({'error': 'Failed to cleanup subdomain'}), 500
            
    except Exception as e:
        logger.error(f"Error cleaning up subdomain: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/status/<subdomain>', methods=['GET'])
def check_status(subdomain):
    manager = get_tunnel_manager()
    if not manager:
        return jsonify({'error': 'Configuration not available'}), 400
    
    try:
        status = manager.status_check(subdomain)
        return jsonify(status)
        
    except Exception as e:
        logger.error(f"Error checking status: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/config')
def config_page():
    return render_template('config.html')


@app.route('/api/config', methods=['POST'])
def save_config():
    data = request.get_json()
    
    api_token = data.get('api_token')
    zone_id = data.get('zone_id')
    account_id = data.get('account_id')
    
    if not all([api_token, zone_id, account_id]):
        return jsonify({'error': 'All fields are required'}), 400
    
    try:
        api = CloudflareTunnelAPI(api_token, zone_id, account_id)
        if api.verify_credentials():
            zone_name = api._get_zone_name()
            
            os.environ['CLOUDFLARE_API_TOKEN'] = api_token
            os.environ['CLOUDFLARE_ZONE_ID'] = zone_id
            os.environ['CLOUDFLARE_ACCOUNT_ID'] = account_id
            
            return jsonify({
                'message': 'Configuration saved successfully',
                'zone_name': zone_name
            })
        else:
            return jsonify({'error': 'Invalid credentials'}), 400
            
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/network-info', methods=['GET'])
def get_network_info():
    local_ip = get_local_ip()
    
    try:
        import netifaces
        interfaces = []
        for interface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(interface)
            if netifaces.AF_INET in addrs:
                for addr in addrs[netifaces.AF_INET]:
                    ip = addr['addr']
                    if not ip.startswith('127.'):
                        interfaces.append({
                            'interface': interface,
                            'ip': ip,
                            'is_primary': ip == local_ip
                        })
    except ImportError:
        interfaces = [{'interface': 'auto-detected', 'ip': local_ip, 'is_primary': True}]
    
    return jsonify({
        'primary_ip': local_ip,
        'interfaces': interfaces
    })


@app.route('/api/tunnels/<tunnel_id>/start', methods=['POST'])
def start_tunnel(tunnel_id):
    config = load_config()
    if not config:
        return jsonify({'error': 'Configuration not available'}), 400
    
    try:
        api = CloudflareTunnelAPI(config.api_token, config.zone_id, config.account_id)
        tunnel_info = api.get_tunnel_info(tunnel_id)
        
        if not tunnel_info:
            return jsonify({'error': 'Tunnel not found'}), 404
        
        tunnel_token = tunnel_info.get('token')
        if not tunnel_token:
            return jsonify({'error': 'Tunnel token not available'}), 400
        
        result = tunnel_manager.start_tunnel(
            tunnel_token, 
            tunnel_id, 
            tunnel_info.get('name', f'tunnel-{tunnel_id}')
        )
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error starting tunnel: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tunnels/<tunnel_id>/stop', methods=['POST'])
def stop_tunnel(tunnel_id):
    try:
        result = tunnel_manager.stop_tunnel(tunnel_id)
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error stopping tunnel: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tunnels/<tunnel_id>/status', methods=['GET'])
def get_tunnel_status(tunnel_id):
    try:
        status = tunnel_manager.get_tunnel_status(tunnel_id)
        return jsonify(status)
        
    except Exception as e:
        logger.error(f"Error getting tunnel status: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tunnels/<tunnel_id>/logs', methods=['GET'])
def get_tunnel_logs(tunnel_id):
    try:
        lines = request.args.get('lines', 50, type=int)
        logs = tunnel_manager.get_tunnel_logs(tunnel_id, lines)
        return jsonify({'logs': logs})
        
    except Exception as e:
        logger.error(f"Error getting tunnel logs: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tunnels/running', methods=['GET'])
def list_running_tunnels():
    try:
        running_tunnels = tunnel_manager.list_running_tunnels()
        return jsonify({'running_tunnels': running_tunnels})
        
    except Exception as e:
        logger.error(f"Error listing running tunnels: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tunnels/stop-all', methods=['POST'])
def stop_all_tunnels():
    try:
        results = tunnel_manager.stop_all_tunnels()
        return jsonify({'results': results})
        
    except Exception as e:
        logger.error(f"Error stopping all tunnels: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tunnels/cleanup', methods=['POST'])
def cleanup_old_tunnels():
    config = load_config()
    if not config:
        return jsonify({'error': 'Configuration not available'}), 400
    
    try:
        data = request.get_json() or {}
        confirm = data.get('confirm', False)
        
        if not confirm:
            return jsonify({'error': 'Confirmation required'}), 400
        
        api = CloudflareTunnelAPI(config.api_token, config.zone_id, config.account_id)
        tunnels = api.list_tunnels()
        
        running_tunnels = tunnel_manager.list_running_tunnels()
        running_tunnel_ids = {t['tunnel_id'] for t in running_tunnels}
        
        deleted_count = 0
        errors = []
        
        for tunnel in tunnels:
            tunnel_id = tunnel['id']
            tunnel_name = tunnel.get('name', 'Unknown')
            
            if tunnel_id in running_tunnel_ids:
                continue
            
            try:
                tunnel_manager.stop_tunnel(tunnel_id)
                
                if api.delete_tunnel(tunnel_id):
                    deleted_count += 1
                    logger.info(f'Cleaned up tunnel: {tunnel_name} ({tunnel_id})')
                else:
                    errors.append(f'Failed to delete tunnel: {tunnel_name}')
            except Exception as e:
                errors.append(f'Error deleting tunnel {tunnel_name}: {str(e)}')
        
        return jsonify({
            'success': True,
            'message': f'Cleaned up {deleted_count} tunnels',
            'deleted_count': deleted_count,
            'errors': errors
        })
        
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    print(f"🚀 Starting Cloudflare Tunnel Manager")
    print(f"🌐 Access the web interface at: http://localhost:{port}")
    print(f"🔧 Local IP detected: {get_local_ip()}")
    
    app.run(host='0.0.0.0', port=port, debug=debug)
