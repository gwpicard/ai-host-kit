"""Verify that Place regressions enter baseline commands and fail as intended."""
import argparse
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import traceback

from checks import ROOT


# Each case runs in a fresh interpreter so baseline and current modules cannot
# leak between cases. Fixture helpers may come from the current test tree;
# command entry must come from the supplied source tree.
CASES = [
    ('place_guidance_checks.py','summary','setup.py','summary','Summary omitted name: not set -> test-place'),
    ('place_guidance_checks.py','approval','setup.py','approve','Approval still requires the approve prefix instead of the visible checksum alone'),
    ('place_guidance_checks.py','effect','setup.py','prepare','Prepare printed the effect before approval'),
    ('place_guidance_checks.py','lane_effect','lane.py','prepare','Lane prepare duplicated the effect'),
    ('place_guidance_checks.py','paths','setup.py','plan','Plan command did not choose a default path:'),
    ('place_guidance_checks.py','bootstrap','setup.py','bootstrap','Bootstrap did not discover the approved node:'),
    ('place_guidance_checks.py','guidance','setup.py','apply','Apply guidance omitted the cloud-init wait'),
    ('place_prerequisite_checks.py','prerequisites','setup.py','preflight','Preflight command did not accept valid read prerequisites:'),
    ('place_prerequisite_checks.py','oauth_stage','setup.py','run','Register did not exchange the read credential for services:read:'),
    ('place_prerequisite_checks.py','update_effects','setup.py','prepare','Prepared docktail effect omitted update_check=true'),
    ('place_prerequisite_checks.py','installer','setup.py','install-tools','Installer result differed for good:'),
    ('place_prerequisite_checks.py','pages','setup.py','console','Console command omitted versioned page guidance:'),
    ('place_prerequisite_checks.py','retirement_pages','retire.py',None,'Retirement guidance omitted Delete service'),
]


def worker(source, output, index):
    suite,case,*_=CASES[index]
    scripts=source/'.agents/skills/recipes/coolify-hetzner/scripts'
    trace=output/(case+'.commands.jsonl')
    trace.touch()
    def entered(frame,event,arg):
        code=frame.f_code
        if event=='call' and code.co_name=='main' and Path(code.co_filename).resolve().parent==scripts:
            with trace.open('a') as stream:
                stream.write(json.dumps(dict(file=Path(code.co_filename).name,args=sys.argv[1:]))+'\n')
    os.environ.update(GUIDANCE_SOURCE_ROOT=str(source),PREREQUISITE_SOURCE_ROOT=str(source),
                      PLACE_STAGE_RECIPE=str(scripts.parent))
    sys.setprofile(entered)
    sys.argv=[suite,'--case',case]
    try:
        runpy.run_path(str(ROOT/'.agents/tests/lib'/suite),run_name='__main__')
    except BaseException as error:
        frames=traceback.extract_tb(error.__traceback__)
        result=dict(type=type(error).__name__,message=str(error),
                    file=frames[-1].filename,function=frames[-1].name)
    else:result=dict(type='returned',message='Case returned without an assertion')
    finally:sys.setprofile(None)
    (output/(case+'.failure.json')).write_text(json.dumps(result,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True,help='Unmodified baseline source tree')
    parser.add_argument('--output',type=Path,required=True,help='New folder for command traces and failures')
    parser.add_argument('--worker',type=int,help=argparse.SUPPRESS)
    args=parser.parse_args();source=args.source.resolve();output=args.output.resolve()
    if args.worker is not None:
        worker(source,output,args.worker);return 0
    assert source!=ROOT,'Supply a separate baseline source tree'
    output.mkdir(parents=True,exist_ok=False)
    failed=[]
    for index,(suite,case,command,verb,message) in enumerate(CASES):
        result=subprocess.run([sys.executable,__file__,'--source',str(source),'--output',str(output),'--worker',str(index)],
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=180)
        (output/(case+'.log')).write_text(result.stdout)
        failure=output/(case+'.failure.json');trace=output/(case+'.commands.jsonl')
        evidence=json.loads(failure.read_text()) if failure.exists() else {}
        entries=[json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
        reached=any(entry['file']==command and (verb is None or entry['args'][0]==verb) for entry in entries)
        intended=(evidence.get('type')=='AssertionError' and evidence.get('message','').startswith(message)
                  and Path(evidence.get('file','')).name==suite)
        if result.returncode or not reached or not intended:
            failed.append(case)
            print('FAILED '+case+': '+json.dumps(evidence),flush=True)
        else:print(case+': entered '+command+(' '+verb if verb else '')+'; '+message,flush=True)
    assert not failed,'Baseline harness failed for: '+', '.join(failed)
    print('All baseline cases reached their commands and failed on the intended assertions.')
    return 0


if __name__=='__main__':sys.exit(main())
