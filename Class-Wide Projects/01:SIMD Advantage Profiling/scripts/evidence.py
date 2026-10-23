#!/usr/bin/env python3
"""Collect candidate SIMD evidence; a human must inspect each kernel's loop."""
import argparse, pathlib, re
ROOT=pathlib.Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--build',type=pathlib.Path,default=ROOT/'build');a=p.parse_args()
parts=['# Vectorization evidence checklist\n',
       'This is a search aid, not proof that every runtime path is vectorized. Inspect the enclosing symbol, loop back-edge, branch for stride/alignment and scalar tail. Packed instructions outside the selected loop do not prove its reduction was vectorized.\n']
for variant in ('scalar','generic','scalar_native','native'):
    folder=a.build/variant;parts.append(f'## {variant}\n')
    for source in ('kernels','strict_dot'):
        text=(folder/f'{source}.disasm.txt').read_text() if (folder/f'{source}.disasm.txt').exists() else ''
        packed=[];symbol=''
        for line in text.splitlines():
            if re.match(r'^[0-9a-f]+ <',line):symbol=line
            if re.search(r'\b(v?(?:add|mul|sub|div)(?:ps|pd)|vfmadd\w*(?:ps|pd)|vgather\w*)\b',line):
                packed.append(symbol+'\n'+line)
        parts.append(f'### {source}\nCandidate packed arithmetic instructions: {len(packed)}.\n')
        if packed:parts.append('```text\n'+'\n'.join(packed[:30])+'\n```\n')
        else:parts.append('No packed arithmetic found by the heuristic; inspect the full disassembly.\n')
    for name in ('kernels.vectorization.txt','strict.vectorization.txt','compile-kernels.log','compile-strict.log'):
        file=folder/name
        if file.exists():
            lines=[x for x in file.read_text().splitlines() if re.search('vectorized|not vectorized|remark:',x)]
            if lines:parts.append(f'{name}\n\n```text\n'+'\n'.join(lines[:25])+'\n```\n')
(a.build/'evidence.md').write_text('\n'.join(parts))
print(f'Evidence index: {a.build / "evidence.md"}')
