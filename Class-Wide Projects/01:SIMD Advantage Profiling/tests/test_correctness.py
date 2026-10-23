#!/usr/bin/env python3
"""Cross-build correctness at vector boundaries, shifted starts and stride holes."""
import argparse, pathlib, subprocess, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--build',type=pathlib.Path,default=ROOT/'build');p.add_argument('--full',action='store_true');a=p.parse_args()
    count=0
    for variant in ('scalar','generic','scalar_native','native'):
        for kernel in ('saxpy','dot','mul','stencil','bandwidth','strictdot'):
            for dtype in ('f32','f64'):
                sizes=[1,7,8,9,15,16,17,33,257] if a.full else [1,7,17,257]
                for n in sizes:
                    for stride,shift in ([(s,o) for s in (1,2,4,8) for o in (0,1,7)] if a.full else [(1,0),(1,1),(2,7),(4,1),(8,0)]):
                        patterns=('positive','alternating') if kernel in ('dot','strictdot') else ('positive',)
                        for pattern in patterns:
                            cmd=[str((a.build/variant/'benchmark').resolve()),'--validate-only','--kernel',kernel,'--dtype',dtype,'--n',str(n),'--stride',str(stride),'--shift',str(shift),'--pattern',pattern]
                            r=subprocess.run(cmd,text=True,capture_output=True)
                            if r.returncode or not r.stdout.startswith('PASS,'):
                                raise RuntimeError(f'{cmd}\n{r.stdout}\n{r.stderr}')
                            count+=1
    executable=str((a.build/'native'/'benchmark').resolve())
    for bad in [['--n','0'],['--n','-1'],['--stride','3'],['--shift','64'],['--samples','0'],['--seconds','nan'],['--kernel','bad'],['--dtype','int32'],['--n','17garbage']]:
        if subprocess.run([executable]+bad,capture_output=True).returncode==0:raise RuntimeError(f'accepted invalid arguments: {bad}')
    print(f'PASS: {count} reference, halo, guard, hole and cancellation cases; invalid arguments rejected.')
if __name__=='__main__':main()
