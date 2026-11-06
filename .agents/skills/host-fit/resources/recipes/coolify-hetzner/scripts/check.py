"""Read a place from this computer. Never refresh state or call a write tool."""
import argparse
import importlib.util
import json
from pathlib import Path
import socket
import sys
import urllib.request
from place import check_place, tailnet_address


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Redirect refused; no credential was forwarded.")


def load_reader():
    for parent in Path(__file__).resolve().parents:
        source = parent / 'host-fit/resources/record_validation.py'
        if source.is_file():
            spec = importlib.util.spec_from_file_location('reader', source)
            reader = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(reader)
            reader.ROOT = source.parent
            return reader
    raise ValueError('The installed record reader is missing.')


def outside_probe(host, port):
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except (ConnectionRefusedError, socket.timeout):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', default='hosting/place-record.json')
    parser.add_argument('--mcp-package', required=True, help='Local installed MCP package.json; no package is fetched.')
    args = parser.parse_args()
    try:
        reader = load_reader()
        if reader.validate('place-record', args.record):
            return 1
        record = reader.read_json(args.record)
        package = reader.read_json(args.mcp_package)
        if package.get('name') != '@masonator/coolify-mcp':
            raise ValueError('The local package is not the pinned Coolify MCP.')
        # API version is an authenticated read. Token is entered by the person;
        # no credential helper, environment file or keychain is read.
        from api import approval_gate
        gate = approval_gate()
        with gate.terminal() as tty:
            token = gate.typed(tty, 'Coolify read token (hidden): ')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        def coolify(address):
            url = 'http://' + tailnet_address(address) + ':8000/api/v1/version'
            request = urllib.request.Request(url, headers={'Authorization':'Bearer ' + token})
            with opener.open(request, timeout=10) as response:
                text = response.read(4096).decode().strip()
                try: return json.loads(text)
                except ValueError: return text
        rows = check_place(record, outside_probe, coolify, lambda:package.get('version'))
        for name, status in rows:
            print(name + ': ' + status)
        return 0 if all(status == 'passed' for _, status in rows) else 1
    except (OSError, ValueError, KeyError, TypeError):
        print('could not run: place inputs or read transport failed; values are withheld.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
