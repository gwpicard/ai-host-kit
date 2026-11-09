"""Place operations. Transports are supplied by the caller; no implicit credentials."""
# Launch order, port probes and retirement checks adapted from coolify-launchpad.
# Lanes and docktail port checks adapted from coolify-devops; see docs/SOURCES.md.
import os
import uuid
import hashlib
import ipaddress
import json
from pathlib import Path
import socket
import sys

PINS = dict(coolify="4.3.23", mcp="3.9.0", docktail="1.8.6", hcloud="1.70.2")
SCOPES = {"read", "read:sensitive", "write", "deploy"}
PROBE_PORTS = {22, 80, 443, 8000, 8080, 6001, 6002}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def attempt_effect(effect, observed):
    return dict(effect, observed=observed, attempt=uuid.uuid4().hex)


def journal_identity(journal):
    # Numeric digest bytes bind the directory without retaining private paths.
    return list(bytes.fromhex(fingerprint(str(Path(journal).resolve()))))


def start_attempt(effect, approval, journal=None):
    # An exclusive, durable receipt consumes this approval before any write.
    path = Path(journal or 'hosting/place-attempts') / (fingerprint(effect) + '.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as out:
        json.dump(dict(effect_sha256=fingerprint(effect), status='uncertain'), out)
        out.flush()
        os.fsync(out.fileno())
    descriptor=os.open(path.parent,os.O_RDONLY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)
    return path


def finish_attempt(path):
    # A crash before this update retains the uncertainty marker.
    with path.open('r+') as out:
        receipt=json.load(out)
        receipt['status']='completed'
        out.seek(0); json.dump(receipt,out); out.truncate()
        out.flush(); os.fsync(out.fileno())


def tailnet_address(address):
    require(ipaddress.ip_address(address) in ipaddress.ip_network("100.64.0.0/10"),
            "Coolify administration must use a tailnet IPv4 address.")
    return address


def ownership(record, resources, partial=False):
    expected = record["infrastructure"]
    name = record["place"]["name"]
    require((bool(resources) and set(resources) <= {"server", "firewall", "ssh_key"}) if partial else set(resources) == {"server", "firewall", "ssh_key"}, "Read all three owned resources.")
    for kind, resource in resources.items():
        require(str(resource["id"]) == str(expected[kind + "_id"]), "Resource identity differs from this place record.")
        require(resource.get("labels") == {"purpose": "ai-host-kit", "place": name},
                "Resource ownership labels differ from this place record.")
        require(resource["name"] == ("coolify" if kind == "firewall" else name),
                "Resource name differs from this place record.")


def lane_rules(lane, ports):
    require(lane in ("internal", "public"), "Choose internal or public access.")
    require(isinstance(ports, list) and len(set(ports)) == len(ports)
            and all(type(p) is int and p in (80, 443) for p in ports),
            "Only explicitly approved public web ports 80 and 443 are supported.")
    require(lane == "public" or not ports, "An internal lane has no public ports.")
    return [dict(direction="in", protocol="tcp", port=str(port), source_ips=["0.0.0.0/0"])
            for port in sorted(ports)]


def lane_effect(record, lane, ports):
    return dict(action="set-lane", place_sha256=fingerprint(record),
                firewall_id=record["infrastructure"]["firewall_id"],
                lane=lane, rules=lane_rules(lane, ports),
                effect="Replace inbound rules for " + record["place"]["name"] + "; public TCP ports: " + (", ".join(map(str, sorted(ports))) or "none")
                + ". SSH and Coolify administration stay on the tailnet.")


def set_lane(record, resources, lane, ports, approval, api, gate, effect=None, journal=None):
    ownership(record, resources)
    # An authenticated tailnet read proves there is an account. It does not
    # prove that the intended person was the first administrator.
    tailnet_address(record["infrastructure"]["tailnet_ipv4"])
    require(api.coolify_team() is not None, "Claim the administrator over the tailnet first.")
    require(api.registration_closed(), "Registration is still open or could not be read. Claim the administrator first.")
    observed = api.firewall_rules(record["infrastructure"]["firewall_id"])
    print('Observed firewall rules: '+json.dumps(observed,sort_keys=True))
    require(effect is not None and effect.get('observed') == observed
            and {k:v for k,v in effect.items() if k not in ('observed','attempt','journal')} == lane_effect(record,lane,ports)
            and bool(effect.get('attempt')), 'Read and prepare a fresh lane effect before applying.')
    require(journal is None or effect.get('journal') == journal_identity(journal),
            'Use the record directory bound to this prepared lane attempt.')
    gate(effect, approval)
    receipt = start_attempt(effect, approval, journal)
    api.set_firewall(effect["firewall_id"], effect["rules"])
    require(api.firewall_rules(effect["firewall_id"]) == effect["rules"], "Firewall read-back differs.")
    finish_attempt(receipt)
    return effect


def docktail_labels(name, container_port):
    require(name.isascii() and name.replace("-", "").isalnum(), "Use a plain service name.")
    require(type(container_port) is int and 1 <= container_port <= 65535, "Invalid container port.")
    return {"docktail.service.enable": "true", "docktail.service.name": name,
            "docktail.service.port": str(container_port), "docktail.service.service-port": "443"}


def docktail_effect(record, name, container_port, observed):
    labels = docktail_labels(name, container_port)
    return attempt_effect(dict(action="register-docktail", place_sha256=fingerprint(record), labels=labels,
                  image="ghcr.io/marvinvr/docktail:" + PINS["docktail"],
                  effect="Register internal docktail service " + name + " on tailnet TCP 443 to container port " + str(container_port) + ", with no published ports."), observed)


def register_docktail(record, name, container_port, approval, api, gate, effect=None, journal=None):
    labels = docktail_labels(name, container_port)
    before = api.service_definition(name)
    require(before is None or before.get("ports") == ["tcp:443"],
            "Existing service has different write-once ports. Repair requires a separate approval.")
    require(effect is not None and effect.get('observed') == before and bool(effect.get('attempt')),
            'Read and prepare a fresh docktail effect before applying.')
    expected=docktail_effect(record,name,container_port,before)
    require({k:v for k,v in effect.items() if k not in ('attempt',)} ==
            {k:v for k,v in expected.items() if k not in ('attempt',)}, 'The docktail effect differs.')
    gate(effect, approval)
    receipt = start_attempt(effect, approval, journal)
    api.register_service(effect)
    after = api.service_definition(name)
    require(after is not None and after.get("ports") == ["tcp:443"], "Service definition does not declare TCP 443.")
    require(api.service_ready(name), "Service is not approved and ready.")
    finish_attempt(receipt)
    return effect


def scoped_mcp(scopes, version):
    require(set(scopes) == SCOPES and len(scopes) == len(SCOPES),
            "Use read, read:sensitive, write and deploy scopes only; root is refused.")
    require(version == PINS["mcp"], "MCP version differs from the pin.")
    return dict(command="npx", args=["--yes", "@masonator/coolify-mcp@" + PINS["mcp"]])


def check_place(record, probe, coolify_get, mcp_version):
    infra = record["infrastructure"]
    require(all(rule['protocol'] == 'tcp' and rule['sources'] == ['0.0.0.0/0']
                and set(rule['ports']) <= {80, 443} for rule in record['firewall']['rules']),
            "Only the approved web lane can be checked as public access.")
    approved = {p for rule in record["firewall"]["rules"] for p in rule["ports"]}
    rows = []
    # Probe every approved port and the fixed administrative ports, including 8080.
    for port in sorted(PROBE_PORTS | approved):
        try:
            observed = probe(infra["public_ipv4"], port)
            status = "passed" if type(observed) is bool and observed == (port in approved) else "failed"
        except (OSError, TimeoutError):
            status = "could not decide"
        rows.append(("outside TCP " + str(port), status))
    try:
        address = tailnet_address(infra["tailnet_ipv4"])
        rows.append(("Coolify over the tailnet", "passed" if coolify_get(address) == PINS["coolify"] else "failed"))
    except (ValueError, OSError, TimeoutError):
        rows.append(("Coolify over the tailnet", "could not decide"))
    try:
        rows.append(("MCP version", "passed" if mcp_version() == PINS["mcp"] else "failed"))
    except (OSError, TimeoutError):
        rows.append(("MCP version", "did not run"))
    return rows


def retire(record, resources, saved_destroy, approval, api, gate, confirm, partial=False):
    ownership(record, resources, partial)
    require(not record["tools"], "Export and retire every tool before retiring this place.")
    name = record["place"]["name"]
    require(confirm(name) == name, "The typed place name did not match.")
    # The caller uses the saved-plan gate, which independently checks approval,
    # plan-time destination identity and the exact encrypted destroy-plan bytes.
    gate(saved_destroy, approval)
    def inventory(kind):
        try: return api.inventory(kind)
        except (OSError,ValueError,KeyError,TypeError):
            if kind != 'images': raise
            return None
    return {kind: inventory(kind) for kind in (
        "servers", "firewalls", "ssh_keys", "volumes", "networks", "floating_ips",
        "primary_ips", "load_balancers", "placement_groups", "certificates", "images")}


def write_record(record, destination, validate):
    validate(record)
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite another person's record.
    import os
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as out:
        json.dump(record, out, indent=2)
        out.write("\n")


def destroy_plan_matches(record, plan, partial=False):
    require(not plan.get('deferred_changes') and plan.get('complete') is not False,
            "Resolve the destroy plan before retirement.")
    types = {"hcloud_server":"server", "hcloud_firewall":"firewall", "hcloud_ssh_key":"ssh_key"}
    found = {}
    for item in plan.get("resource_changes", []):
        change = item["change"]
        if change["actions"] == ["no-op"]:
            continue
        require(item.get("type") in types and change["actions"] == ["delete"],
                "Retirement accepts only the three owned resource deletions.")
        kind = types[item["type"]]
        require(kind not in found, "The destroy plan has duplicate place resources.")
        if partial:
            address = 'module.place.' + item['type'] + ('.coolify' if kind == 'firewall' else '.place')
            require(item.get('address') == address, 'Recovery only deletes resources at the kit-created addresses.')
        found[kind] = change["before"]
    ownership(record, found, partial)
    return found


def partial_record(state, values):
    # The generated root has exactly these three managed addresses. Never adopt
    # other state resources, even if their labels happen to match this place.
    record=dict(place=state['config']['place'], tools=[], infrastructure={})
    expected={'module.place.hcloud_server.place':'server',
              'module.place.hcloud_firewall.coolify':'firewall',
              'module.place.hcloud_ssh_key.place':'ssh_key'}
    found={}
    def walk(module):
        for item in module.get('resources',[]):
            if item.get('mode') != 'managed': continue
            require(item.get('address') in expected, 'Recovery refuses state resources the kit did not create.')
            kind={'hcloud_server':'server','hcloud_firewall':'firewall','hcloud_ssh_key':'ssh_key'}[item['type']]
            require(kind not in found, 'Recovery state has duplicate resources.')
            found[kind]=item['values']
            record['infrastructure'][kind+'_id']=item['values']['id']
        for child in module.get('child_modules',[]): walk(child)
    walk(values['root_module'])
    ownership(record,found,partial=True)
    return record
