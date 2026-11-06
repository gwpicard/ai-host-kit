"""Retire only the owned resources in an approved encrypted destroy plan."""
import argparse
import getpass
import json
from pathlib import Path
import sys
from api import API, approval_gate
from check import load_reader
from place import destroy_plan_matches, retire


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record',default='hosting/place-record.json')
    parser.add_argument('--plan',required=True)
    parser.add_argument('--approval',required=True)
    args=parser.parse_args()
    try:
        reader=load_reader()
        if reader.validate('place-record',args.record): return 1
        record=reader.read_json(args.record)
        gate=approval_gate()
        # Read only the same encrypted bytes that the saved-plan gate will apply.
        gate.require_encryption(); gate.check_version()
        with gate.saved_plan(args.plan) as (snapshot,sha):
            gate.planned_identity(args.plan,sha)
            shown=gate.tofu('show','-json',snapshot)
            if shown.returncode: raise ValueError('Destroy plan could not be read.')
            destroy_plan_matches(record,json.loads(shown.stdout))
        api=API(record,getpass.getpass('Hetzner project token (hidden): '))
        def confirm(name):
            with gate.terminal() as tty:
                return gate.typed(tty,'This destroys the place and its disk. Type '+name+': ')
        def apply(plan,approval):
            # Re-read and match owned deletions immediately before gated apply.
            with gate.saved_plan(plan) as (snapshot,sha):
                shown=gate.tofu('show','-json',snapshot)
                if shown.returncode: raise ValueError('Destroy plan could not be read.')
                destroy_plan_matches(record,json.loads(shown.stdout))
            gate.apply(plan,approval)
        remaining=retire(record,api.owned_resources(),args.plan,args.approval,api,apply,confirm)
        for kind,items in remaining.items():
            print(kind+': '+(', '.join(str(item['id']) for item in items) or 'none'))
        print('Object Storage and DNS are outside this inventory. Review them in the Hetzner console.')
        print('Tailscale admin console > Machines > this place > Remove remains a separate approved action.')
        return 0
    except (OSError,ValueError,KeyError,TypeError):
        print('Refused: retirement inputs, ownership, approval or transport failed. Inspect the place privately; values are withheld.',file=sys.stderr)
        return 1


if __name__=='__main__': sys.exit(main())
