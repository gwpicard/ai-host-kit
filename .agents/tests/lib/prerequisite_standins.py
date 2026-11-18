"""Read-only boundaries for command tests whose subject follows preflight."""
from contextlib import contextmanager
from unittest.mock import patch


POLICY = dict(tagOwners={'tag:server':['autogroup:admin'], 'tag:container':['tag:server']},
    autoApprovers=dict(services={'tag:container':['tag:server']}),
    ssh=[dict(action='check',src=['autogroup:admin'],dst=['tag:server'],users=['root'])])


@contextmanager
def ready(flow):
    def read(self, method, url, token):
        assert method=='GET' and token=='synthetic-preflight-only'
        base='https://api.tailscale.com/api/v2/tailnet/-/'
        return {base+'acl':POLICY, base+'dns/preferences':dict(magicDNS=True),
                base+'settings':dict(httpsEnabled=True)}[url]
    with patch.object(flow.preflight,'bucket_read'), patch.object(flow.toolchain,'verify_tools'), \
         patch.object(flow.preflight,'read_token',return_value='synthetic-preflight-only'), \
         patch.object(flow.preflight.API,'request',read):
        yield
