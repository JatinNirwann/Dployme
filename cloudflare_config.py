
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class CloudflareConfig:
    api_token: str
    zone_id: str
    account_id: str
    
    @classmethod
    def from_env(cls) -> 'CloudflareConfig':
        return cls(
            api_token=os.getenv('CLOUDFLARE_API_TOKEN', ''),
            zone_id=os.getenv('CLOUDFLARE_ZONE_ID', ''),
            account_id=os.getenv('CLOUDFLARE_ACCOUNT_ID', '')
        )
    
    @classmethod
    def from_file(cls, config_path: str) -> 'CloudflareConfig':
        import json
        with open(config_path, 'r') as f:
            data = json.load(f)
        return cls(**data)
    
    def validate(self) -> bool:
        return bool(self.api_token and self.zone_id and self.account_id)
    
    def to_dict(self) -> dict:
        return {
            'api_token': self.api_token,
            'zone_id': self.zone_id,
            'account_id': self.account_id
        }


EXAMPLE_CONFIG = {
    "api_token": "your_cloudflare_api_token_here",
    "zone_id": "your_zone_id_here", 
    "account_id": "your_account_id_here"
}

SETUP_INSTRUCTIONS = """
To get your Cloudflare credentials:

1. API Token:
   - Go to https://dash.cloudflare.com/profile/api-tokens
   - Click "Create Token"
   - Use "Custom token" template
   - Set permissions:
     * Zone:Zone:Read
     * Zone:DNS:Edit
     * Account:Cloudflare Tunnel:Edit
   - Add zone resource: Include -> Zone -> Your domain
   - Add account resource: Include -> Account -> Your account

2. Zone ID:
   - Go to your domain in Cloudflare dashboard
   - Scroll down to "API" section in the right sidebar
   - Copy the Zone ID

3. Account ID:
   - Go to Cloudflare dashboard
   - In the right sidebar, find "Account ID"
   - Copy the Account ID

Environment variables (recommended):
export CLOUDFLARE_API_TOKEN="your_token"
export CLOUDFLARE_ZONE_ID="your_zone_id"
export CLOUDFLARE_ACCOUNT_ID="your_account_id"
"""

if __name__ == '__main__':
    print(SETUP_INSTRUCTIONS)
