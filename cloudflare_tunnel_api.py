import requests
import json
import logging
import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime


class CloudflareTunnelAPI:
    
    def __init__(self, api_token: str, zone_id: str, account_id: str):
        self.api_token = api_token
        self.zone_id = zone_id
        self.account_id = account_id
        self.base_url = 'https://api.cloudflare.com/client/v4'
        self.headers = {
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json'
        }
        self.logger = logging.getLogger(__name__)
    
    def create_tunnel(self, tunnel_name: str, secret: Optional[str] = None) -> Dict[str, Any]:
        if not secret:
            secret = str(uuid.uuid4()).replace('-', '')
        
        url = f'{self.base_url}/accounts/{self.account_id}/cfd_tunnel'
        
        data = {
            'name': tunnel_name,
            'tunnel_secret': secret
        }
        
        try:
            response = requests.post(url, json=data, headers=self.headers)
            response.raise_for_status()
            
            result = response.json()
            if result.get('success'):
                tunnel_info = result['result']
                self.logger.info(f'Created tunnel: {tunnel_name} with ID: {tunnel_info["id"]}')
                return tunnel_info
            else:
                raise Exception(f"API error: {result.get('errors', 'Unknown error')}")
        
        except requests.RequestException as e:
            self.logger.error(f'Error creating tunnel: {e}')
            raise Exception(f'Failed to create tunnel: {e}')
    
    def create_tunnel_route(self, tunnel_id: str, subdomain: str, localhost_port: int) -> Dict[str, Any]:
        zone_name = self._get_zone_name()
        hostname = f'{subdomain}.{zone_name}'
        
        url = f'{self.base_url}/accounts/{self.account_id}/cfd_tunnel/{tunnel_id}/configurations'
        
        data = {
            'config': {
                'ingress': [
                    {
                        'hostname': hostname,
                        'service': f'http://localhost:{localhost_port}'
                    },
                    {
                        'service': 'http_status:404'
                    }
                ]
            }
        }
        
        try:
            response = requests.put(url, json=data, headers=self.headers)
            response.raise_for_status()
            
            result = response.json()
            if result.get('success'):
                self.logger.info(f'Created route for {hostname} -> localhost:{localhost_port}')
                return result['result']
            else:
                raise Exception(f"API error: {result.get('errors', 'Unknown error')}")
        
        except requests.RequestException as e:
            self.logger.error(f'Error creating tunnel route: {e}')
            raise Exception(f'Failed to create tunnel route: {e}')
    
    def create_dns_record(self, subdomain: str, tunnel_id: str) -> Dict[str, Any]:
        zone_name = self._get_zone_name()
        hostname = f'{subdomain}.{zone_name}'
        tunnel_hostname = f'{tunnel_id}.cfargotunnel.com'
        
        url = f'{self.base_url}/zones/{self.zone_id}/dns_records'
        
        data = {
            'type': 'CNAME',
            'name': subdomain,
            'content': tunnel_hostname,
            'ttl': 1,
            'proxied': True
        }
        
        try:
            response = requests.post(url, json=data, headers=self.headers)
            response.raise_for_status()
            
            result = response.json()
            if result.get('success'):
                dns_record = result['result']
                self.logger.info(f'Created DNS record: {hostname} -> {tunnel_hostname}')
                return dns_record
            else:
                raise Exception(f"API error: {result.get('errors', 'Unknown error')}")
        
        except requests.RequestException as e:
            self.logger.error(f'Error creating DNS record: {e}')
            raise Exception(f'Failed to create DNS record: {e}')
    
    def setup_subdomain_tunnel(self, subdomain: str, localhost_port: int, tunnel_name: Optional[str] = None) -> Dict[str, Any]:
        if not tunnel_name:
            tunnel_name = f'{subdomain}-tunnel-{int(datetime.now().timestamp())}'
        
        try:
            tunnel_info = self.create_tunnel(tunnel_name)
            tunnel_id = tunnel_info['id']
            
            route_info = self.create_tunnel_route(tunnel_id, subdomain, localhost_port)
            
            dns_info = self.create_dns_record(subdomain, tunnel_id)
            
            setup_info = {
                'tunnel': tunnel_info,
                'route': route_info,
                'dns': dns_info,
                'subdomain': f'{subdomain}.{self._get_zone_name()}',
                'localhost_port': localhost_port,
                'tunnel_token': tunnel_info.get('token'),
                'setup_complete': True
            }
            
            self.logger.info(f'Successfully setup subdomain tunnel: {subdomain} -> localhost:{localhost_port}')
            return setup_info
        
        except Exception as e:
            self.logger.error(f'Error setting up subdomain tunnel: {e}')
            try:
                if 'tunnel_id' in locals():
                    self.delete_tunnel(tunnel_id)
            except:
                pass
            raise Exception(f'Failed to setup subdomain tunnel: {e}')
    
    def list_tunnels(self) -> List[Dict[str, Any]]:
        url = f'{self.base_url}/accounts/{self.account_id}/cfd_tunnel'
        
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            
            result = response.json()
            if result.get('success'):
                return result.get('result', [])
            
            return []
        
        except requests.RequestException as e:
            self.logger.error(f'Error listing tunnels: {e}')
            return []
    
    def get_tunnel_info(self, tunnel_id: str) -> Optional[Dict[str, Any]]:
        url = f'{self.base_url}/accounts/{self.account_id}/cfd_tunnel/{tunnel_id}'
        
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            
            result = response.json()
            if result.get('success'):
                return result['result']
            
            return None
        
        except requests.RequestException as e:
            self.logger.error(f'Error getting tunnel info: {e}')
            return None
    
    def delete_tunnel(self, tunnel_id: str) -> bool:
        url = f'{self.base_url}/accounts/{self.account_id}/cfd_tunnel/{tunnel_id}'
        
        try:
            response = requests.delete(url, headers=self.headers)
            response.raise_for_status()
            
            result = response.json()
            if result.get('success'):
                self.logger.info(f'Deleted tunnel: {tunnel_id}')
                return True
            else:
                raise Exception(f"API error: {result.get('errors', 'Unknown error')}")
        
        except requests.RequestException as e:
            self.logger.error(f'Error deleting tunnel: {e}')
            return False
    
    def delete_dns_record(self, record_id: str) -> bool:
        url = f'{self.base_url}/zones/{self.zone_id}/dns_records/{record_id}'
        
        try:
            response = requests.delete(url, headers=self.headers)
            response.raise_for_status()
            
            result = response.json()
            if result.get('success'):
                self.logger.info(f'Deleted DNS record: {record_id}')
                return True
            
            return False
        
        except requests.RequestException as e:
            self.logger.error(f'Error deleting DNS record: {e}')
            return False
    
    def cleanup_subdomain_tunnel(self, subdomain: str) -> bool:
        try:
            zone_name = self._get_zone_name()
            hostname = f'{subdomain}.{zone_name}'
            
            dns_records = self._get_dns_records_by_name(subdomain)
            for record in dns_records:
                self.delete_dns_record(record['id'])
            
            tunnels = self.list_tunnels()
            for tunnel in tunnels:
                if subdomain in tunnel.get('name', ''):
                    self.delete_tunnel(tunnel['id'])
            
            self.logger.info(f'Cleaned up subdomain tunnel: {subdomain}')
            return True
        
        except Exception as e:
            self.logger.error(f'Error cleaning up subdomain tunnel: {e}')
            return False
    
    def get_tunnel_token(self, tunnel_id: str) -> Optional[str]:
        tunnel_info = self.get_tunnel_info(tunnel_id)
        if tunnel_info:
            return tunnel_info.get('token')
        return None
    
    def generate_cloudflared_command(self, tunnel_token: str) -> str:
        return f'cloudflared tunnel --token {tunnel_token}'
    
    def verify_setup(self, subdomain: str) -> Dict[str, Any]:
        zone_name = self._get_zone_name()
        hostname = f'{subdomain}.{zone_name}'
        
        verification = {
            'subdomain': hostname,
            'dns_record_exists': False,
            'tunnel_exists': False,
            'accessible': False
        }
        
        dns_records = self._get_dns_records_by_name(subdomain)
        if dns_records:
            verification['dns_record_exists'] = True
            verification['dns_record'] = dns_records[0]
        
        tunnels = self.list_tunnels()
        for tunnel in tunnels:
            if subdomain in tunnel.get('name', ''):
                verification['tunnel_exists'] = True
                verification['tunnel'] = tunnel
                break
        
        return verification
    
    def _get_zone_name(self) -> str:
        url = f'{self.base_url}/zones/{self.zone_id}'
        
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            
            result = response.json()
            if result.get('success'):
                return result['result']['name']
            
            raise Exception('Failed to get zone name')
        
        except requests.RequestException as e:
            self.logger.error(f'Error getting zone name: {e}')
            raise Exception(f'Failed to get zone name: {e}')
    
    def _get_dns_records_by_name(self, subdomain: str) -> List[Dict[str, Any]]:
        zone_name = self._get_zone_name()
        hostname = f'{subdomain}.{zone_name}'
        
        url = f'{self.base_url}/zones/{self.zone_id}/dns_records'
        params = {'name': hostname}
        
        try:
            response = requests.get(url, params=params, headers=self.headers)
            response.raise_for_status()
            
            result = response.json()
            if result.get('success'):
                return result.get('result', [])
            
            return []
        
        except requests.RequestException as e:
            self.logger.error(f'Error getting DNS records: {e}')
            return []
    
    def verify_credentials(self) -> bool:
        url = f'{self.base_url}/user/tokens/verify'
        
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            
            result = response.json()
            if result.get('success'):
                zone_url = f'{self.base_url}/zones/{self.zone_id}'
                zone_response = requests.get(zone_url, headers=self.headers)
                zone_response.raise_for_status()
                
                zone_result = zone_response.json()
                return zone_result.get('success', False)
            
            return False
        
        except requests.RequestException as e:
            self.logger.error(f'Error verifying credentials: {e}')
            return False


class TunnelManager:
    
    def __init__(self, api_token: str, zone_id: str, account_id: str):
        self.tunnel_api = CloudflareTunnelAPI(api_token, zone_id, account_id)
        self.logger = logging.getLogger(__name__)
    
    def quick_setup(self, subdomain: str, port: int) -> Dict[str, Any]:
        try:
            if not self.tunnel_api.verify_credentials():
                raise Exception('Invalid API credentials')
            
            setup_info = self.tunnel_api.setup_subdomain_tunnel(subdomain, port)
            
            if setup_info.get('tunnel', {}).get('token'):
                setup_info['cloudflared_command'] = self.tunnel_api.generate_cloudflared_command(
                    setup_info['tunnel']['token']
                )
            
            return setup_info
        
        except Exception as e:
            self.logger.error(f'Quick setup failed: {e}')
            raise
    
    def status_check(self, subdomain: str) -> Dict[str, Any]:
        return self.tunnel_api.verify_setup(subdomain)
    
    def cleanup(self, subdomain: str) -> bool:
        return self.tunnel_api.cleanup_subdomain_tunnel(subdomain)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    API_TOKEN = 'your_api_token_here'
    ZONE_ID = 'your_zone_id_here'
    ACCOUNT_ID = 'your_account_id_here'
    
    manager = TunnelManager(API_TOKEN, ZONE_ID, ACCOUNT_ID)
    
    try:
        result = manager.quick_setup('myapp', 3000)
        print('Setup complete!')
        print(f"Your app is available at: https://{result['subdomain']}")
        print(f"Run this command to start the tunnel:")
        print(result['cloudflared_command'])
    except Exception as e:
        print(f'Setup failed: {e}')
