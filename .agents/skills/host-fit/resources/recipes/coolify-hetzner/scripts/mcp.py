"""A bounded stdio client for the installed, unmodified Coolify MCP pin."""
import json
import os
from pathlib import Path
import select
import subprocess
import time
from place import PINS, require, scoped_mcp, tailnet_address


class MCP:
    def __init__(self, package, address, token, scopes, observed_abilities=None):
        scoped_mcp(scopes, PINS['mcp'])
        if observed_abilities is not None:
            scoped_mcp(observed_abilities, PINS['mcp'])
        folder = Path(package).resolve().parent
        metadata = json.loads((folder/'package.json').read_text())
        require(metadata.get('name') == '@masonator/coolify-mcp' and metadata.get('version') == PINS['mcp'],
                'Install the pinned MCP package before continuing.')
        # No inherited instance, token-file, proxy, Node option or logging settings.
        child = dict(PATH=os.environ.get('PATH', ''), COOLIFY_BASE_URL='http://'+tailnet_address(address)+':8000',
                     COOLIFY_ACCESS_TOKEN=token)
        self.process = subprocess.Popen(['node',str(folder/'dist/index.js')], env=child,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.buffer = b''
        self.sequence = 0
        try:
            hello = self.request('initialize', dict(protocolVersion='2025-11-25', capabilities={},
                clientInfo=dict(name='ai-host-kit', version='0.0.1')))
            require(hello.get('serverInfo', {}).get('version') == PINS['mcp'], 'The running MCP version differs.')
            self.send(dict(jsonrpc='2.0',method='notifications/initialized'))
            version = self.call('get_mcp_version', {})
            require(version.get('version') == PINS['mcp'], 'The MCP tool version differs.')
        except BaseException:
            self.close()
            raise

    def send(self, value):
        self.process.stdin.write(json.dumps(value).encode()+b'\n')
        self.process.stdin.flush()

    def request(self, method, params):
        self.sequence += 1
        identity = self.sequence
        self.send(dict(jsonrpc='2.0',id=identity,method=method,params=params))
        deadline = time.monotonic()+60
        while time.monotonic() < deadline:
            if b'\n' not in self.buffer:
                ready, _, _ = select.select([self.process.stdout], [], [], max(0,deadline-time.monotonic()))
                require(bool(ready), 'MCP timed out. Inspect the place before retrying a write.')
                chunk = os.read(self.process.stdout.fileno(),65536)
                require(bool(chunk), 'MCP stopped. Inspect the place before retrying a write.')
                self.buffer += chunk
                require(len(self.buffer) <= 4*1024*1024, 'MCP response exceeded the read limit.')
                continue
            line, self.buffer = self.buffer.split(b'\n',1)
            value = json.loads(line)
            # Never approve MCP elicitation or server requests automatically.
            require('method' not in value or 'id' not in value, 'MCP requested another action; stop for review.')
            if value.get('id') == identity:
                require('error' not in value and 'result' in value, 'MCP refused the request; diagnostics withheld.')
                return value['result']
        raise ValueError('MCP timed out; inspect the place before retrying.')

    def call(self, tool, arguments):
        result = self.request('tools/call', dict(name=tool, arguments=arguments))
        require(not result.get('isError'), 'MCP operation failed; diagnostics withheld.')
        for item in result.get('content', []):
            if item.get('type') != 'text': continue
            try:
                value=json.loads(item.get('text',''))
                if isinstance(value,(dict,list)): return value
            except ValueError: pass
        raise ValueError('MCP returned no structured result; inspect the place before retrying.')

    def close(self):
        self.process.terminate()
        try: self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill(); self.process.wait()
        self.process.stdin.close(); self.process.stdout.close()
