"""Prepare or apply an explicit firewall lane effect after separate approval."""
import argparse
import copy
import json
from pathlib import Path
import sys
from api import API, approval_gate, hidden_value
from check import load_reader
from place import lane_effect, set_lane, write_record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','apply'])
    parser.add_argument('--record',default='hosting/place-record.json')
    parser.add_argument('--lane',choices=['internal','public'],required=True)
    parser.add_argument('--port',type=int,action='append',default=[])
    parser.add_argument('--effect',required=True)
    parser.add_argument('--approval')
    parser.add_argument('--new-record')
    args=parser.parse_args()
    try:
        reader=load_reader()
        if reader.validate('place-record',args.record): return 1
        record=reader.read_json(args.record)
        effect=lane_effect(record,args.lane,args.port)
        if args.command=='prepare':
            with open(args.effect,'x') as out: json.dump(effect,out,indent=2)
            print(effect['effect'])
            return 0
        if not args.approval or not args.new_record:
            raise ValueError('Apply requires effect approval and a new record path.')
        gate=approval_gate()
        gate.match_effect(effect,args.approval)
        if reader.read_json(args.effect)!=effect: raise ValueError('The prepared effect differs.')
        # Refuse an existing destination before a cloud write.
        if Path(args.new_record).exists(): raise ValueError('The new record already exists.')
        api=API(record,hidden_value(gate,'Hetzner project token'),hidden_value(gate,'Coolify read token'))
        set_lane(record,api.owned_resources(),args.lane,args.port,args.approval,api,gate.match_effect)
        updated=copy.deepcopy(record)
        updated['firewall']['rules']=[dict(protocol='tcp',ports=[p],sources=['0.0.0.0/0'],purpose='Approved public web access') for p in sorted(args.port)]
        def validate(value):
            loaded=reader.dependencies()
            if loaded is None: raise ValueError('Install the schema requirements.')
            validator,formats=loaded
            schema=reader.read_json(reader.ROOT/'contracts/place-record.schema.json')
            if list(validator(schema,format_checker=formats).iter_errors(value)) or list(reader.secret_fields(value)):
                raise ValueError('The new record failed validation.')
        write_record(updated,args.new_record,validate)
        print('Applied the approved lane and saved a new record for review.')
        return 0
    except (OSError,ValueError,KeyError,TypeError):
        print('Refused: lane inputs, approval or transport failed. Read the place before retrying; values are withheld.',file=sys.stderr)
        return 1


if __name__=='__main__': sys.exit(main())
