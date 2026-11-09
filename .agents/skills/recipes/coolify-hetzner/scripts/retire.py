"""Retire only the owned resources in an approved encrypted destroy plan."""
import argparse
import json
from pathlib import Path
import sys
from api import API, approval_gate, hidden_value
from check import load_reader
from place import destroy_plan_matches, retire, fingerprint


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--partial-progress')
    parser.add_argument('--record',default='hosting/place-record.json')
    parser.add_argument('--plan',required=True)
    parser.add_argument('--approval',required=True)
    args=parser.parse_args()
    try:
        reader=load_reader()
        partial=bool(args.partial_progress)
        if partial:
            progress=reader.read_json(args.partial_progress)
            if Path(progress['root']).resolve()!=Path.cwd().resolve(): raise ValueError('Use the recorded root for partial retirement.')
            record=progress['recovery_record']
        else:
            if reader.validate('place-record',args.record): return 1
            record=reader.read_json(args.record)
        gate=approval_gate()
        # Read only the same encrypted bytes that the saved-plan gate will apply.
        gate.require_encryption(); gate.check_version()
        with gate.saved_plan(args.plan) as (snapshot,sha):
            gate.planned_identity(args.plan,sha)
            shown=gate.tofu('show','-json',snapshot)
            if shown.returncode: raise ValueError('Destroy plan could not be read.')
            destroy_plan_matches(record,json.loads(shown.stdout),partial)
        token=hidden_value(gate,'Hetzner project token')
        if partial and progress.get('provider_plans',{}).get(sha)!=fingerprint(token):
            raise ValueError('The project token differs from the saved plan.')
        api=API(record,token)
        def confirm(name):
            with gate.terminal() as tty:
                return gate.typed(tty,'This destroys the place and its disk. Type '+name+': ')
        def apply(plan,approval):
            # Re-read and match owned deletions immediately before gated apply.
            with gate.saved_plan(plan) as (snapshot,sha):
                shown=gate.tofu('show','-json',snapshot)
                if shown.returncode: raise ValueError('Destroy plan could not be read.')
                destroy_plan_matches(record,json.loads(shown.stdout),partial)
            gate.apply(plan,approval)
        remaining=retire(record,api.owned_resources(partial=True) if partial else api.owned_resources(),args.plan,args.approval,api,apply,confirm,partial)
        print('Destruction completed. Review every inventory category and the later console checks before completing retirement.')
        for kind,items in remaining.items():
            status='unchecked; review in the Hetzner console' if items is None else ('listed: '+', '.join(str(item['id']) for item in items) if items else 'empty')
            print(kind+': '+status)
        print('Images: review snapshot and backup images in the Hetzner console, including retained copies.')
        print('Object Storage and DNS are outside this inventory. Review them in the Hetzner console.')
        plumbing=record['infrastructure'].get('plumbing',{})
        if plumbing:
            print('Tailscale Services > svc:'+plumbing['tailnet_service_name']+' may remain. Review its advertising devices before a separately approved removal.')
        print('Tailscale admin console > Machines > this place > Remove remains a separate approved action.')
        if any(items is None for items in remaining.values()):
            print('Retirement incomplete: destruction completed, but inventory checks remain unchecked.')
            return 2
        return 0
    except (OSError,ValueError,KeyError,TypeError):
        print('Refused: retirement inputs, ownership, approval or transport failed. Inspect the place privately; values are withheld.',file=sys.stderr)
        return 1


if __name__=='__main__': sys.exit(main())
