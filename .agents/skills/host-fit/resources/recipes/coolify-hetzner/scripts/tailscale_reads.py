"""Use a separate OAuth read credential, or an explicitly described fallback."""
import json
import urllib.error
import urllib.parse
import urllib.request
from check import NoRedirect
from place import OperationRefused

SERVICE_SCOPES = ['services:read']
PREFLIGHT_SCOPES = SERVICE_SCOPES + ['policy_file:read', 'dns:read',
    'networking_settings:read', 'devices:core:read', 'devices:posture_attributes:read']


def read_token(gate, preflight=False, fallback=None):
    values = getattr(gate, 'SECRET_VALUES', {})
    if values.get('TAILSCALE_READ_CLIENT_ID') or values.get('TAILSCALE_READ_CLIENT_SECRET'):
        client = gate.secret('TAILSCALE_READ_CLIENT_ID', 'Tailscale read trust credential Client ID', shown=True)
        private = gate.secret('TAILSCALE_READ_CLIENT_SECRET', 'Tailscale read trust credential Client secret')
        scopes = PREFLIGHT_SCOPES if preflight else SERVICE_SCOPES
        data = urllib.parse.urlencode(dict(client_id=client, client_secret=private,
            grant_type='client_credentials', scope=' '.join(scopes))).encode()
        request = urllib.request.Request('https://api.tailscale.com/api/v2/oauth/token', data=data,
            headers={'Content-Type':'application/x-www-form-urlencoded'}, method='POST')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(request, timeout=20) as response:
                result = json.loads(response.read(65536))
        except urllib.error.HTTPError as error:
            # The token endpoint answers 401 when it does not accept the pair.
            if error.code == 401:
                raise OperationRefused('Tailscale rejected the read credential pair: its token endpoint answered HTTP 401. Check that TAILSCALE_READ_CLIENT_ID and TAILSCALE_READ_CLIENT_SECRET come from the same credential and that it has not been revoked. No other Tailscale read was sent; values are withheld.') from None
            raise
        if (not isinstance(result, dict) or not isinstance(result.get('access_token'), str)
                or not result['access_token'] or result.get('token_type','').lower() != 'bearer'
                or type(result.get('expires_in')) is not int or not 0 < result['expires_in'] <= 3600):
            raise OperationRefused('The read trust credential did not return a short-lived bearer token. Check its read scopes; no access-token fallback was attempted.')
        print('Exchanged the read trust credential for a short-lived token; requested only '+', '.join(scopes)+'.')
        return result['access_token']
    if not values.get('TAILSCALE_API_TOKEN'):
        from console_pages import show
        print('No Tailscale read credential is in the protected secrets file. Set TAILSCALE_READ_CLIENT_ID and TAILSCALE_READ_CLIENT_SECRET, which is recommended, or TAILSCALE_API_TOKEN as a full-permission fallback. No Tailscale read has been sent.')
        show('tailscale.read-credential')
    print("Fallback API access tokens carry the creating user's full API permissions, including permitted writes and deletions. Use one day and revoke after setup. A separate read OAuth credential is recommended.")
    token = fallback() if fallback else gate.secret('TAILSCALE_API_TOKEN', 'Tailscale full-permission API access token (fallback)')
    if not token: raise OperationRefused('The Tailscale fallback token is empty. No attempt was recorded.')
    return token
