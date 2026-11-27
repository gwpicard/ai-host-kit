"""Read a place from this computer. Never refresh state or call a write tool."""
import argparse
import http.client
import importlib.util
import json
from pathlib import Path
import socket
import ssl
import sys
import subprocess
import urllib.request
import urllib.error
from place import Refused, check_place, tailnet_address


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise Refused("Redirect refused; no credential was forwarded.")


def load_reader():
    for parent in Path(__file__).resolve().parents:
        source = parent / 'host-fit/resources/record_validation.py'
        if source.is_file():
            spec = importlib.util.spec_from_file_location('reader', source)
            reader = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(reader)
            reader.ROOT = source.parent
            return reader
    raise Refused('The installed record reader is missing.')


def outside_probe(host, port):
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except (ConnectionRefusedError, socket.timeout):
        return False


def public_response(host, port):
    """Return the HTTP status an approved public port answers with. Never read a body."""
    # A bare address has no certificate to verify against, and no credential
    # or cookie is sent. The status is reported as information, not a pass.
    if port == 443:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        connection = http.client.HTTPSConnection(host, port, timeout=5, context=context)
    else:
        connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.request('HEAD', '/')
        return int(connection.getresponse().status)
    finally:
        connection.close()


def report_public_responses(record):
    for port in sorted({p for rule in record['firewall']['rules'] for p in rule['ports']}):
        try:
            status = public_response(record['infrastructure']['public_ipv4'], port)
        except (OSError, http.client.HTTPException, ValueError):
            print('Public TCP ' + str(port) + ': no HTTP response could be read.')
            continue
        note = " Coolify's proxy answers 503 until a tool is routed." if status == 503 else ''
        print('Public TCP ' + str(port) + ' answers HTTP ' + str(status) + '.' + note + ' The response body was not read.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', default='hosting/place-record.json')
    from api import secrets_options, configure_place_secrets, hidden_value
    secrets_options(parser)
    args = parser.parse_args()
    try:
        reader = load_reader()
        if reader.validate('place-record', args.record):
            return 1
        record = reader.read_json(args.record)
        # API version is an authenticated read using the protected file or prompt.
        from api import approval_gate
        gate = approval_gate()
        configure_place_secrets(gate,args,record)
        token = hidden_value(gate,'Coolify read token')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        def coolify(address):
            url = 'http://' + tailnet_address(address) + ':8000/api/v1/version'
            request = urllib.request.Request(url, headers={'Authorization':'Bearer ' + token})
            try:
                with opener.open(request, timeout=10) as response:
                    text = response.read(4096).decode().strip()
                    try: return json.loads(text)
                    except ValueError: return text
            except urllib.error.HTTPError as error:
                from api import report_refusal
                report_refusal(error, gate)
                raise
        rows = check_place(record, outside_probe, coolify)
        from node import read_node, node_rows, ssh_reason
        try:
            rows.extend(node_rows(record, read_node(record['infrastructure']['tailnet_ipv4'])))
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
            rows.append(('Tailnet node and temporary key', 'could not decide'))
            print('Tailnet node read: ' + ssh_reason(error), file=sys.stderr)
        for name, status in rows:
            print(name + ': ' + status)
        report_public_responses(record)
        return 0 if all(status == 'passed' for _, status in rows) else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        from api import report_refusal
        report_refusal(error, locals().get('gate'))
        print('could not run: place inputs or read transport failed; values are withheld.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
