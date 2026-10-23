#!/usr/bin/env python3
"""Reproducible separate-TU builds. Works with GCC or Clang on Linux/WSL x86-64."""
import argparse, datetime, json, pathlib, shlex, shutil, subprocess
ROOT = pathlib.Path(__file__).resolve().parents[1]
VARIANTS = ('scalar', 'generic', 'scalar_native', 'native')

def run(cmd, log=None):
    p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if log:
        log.write_text(p.stdout + p.stderr)
    if p.returncode:
        raise RuntimeError(f"command failed: {shlex.join(cmd)}\n{p.stderr}")
    return p.stdout

def build(cxx, out, sanitize=False):
    out.mkdir(parents=True, exist_ok=True)
    version = run([cxx, '--version'])
    clang = 'clang' in version.lower()
    common = ['-std=c++17', '-Wall', '-Wextra', '-Wpedantic', '-g', '-fno-lto', '-ffp-contract=off']
    if sanitize:
        common += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer']
    commands = []
    def command(args, log=None):
        cmd = [cxx] + args
        commands.append(shlex.join(cmd))
        return run(cmd, log)
    for variant in VARIANTS:
        dst = out / variant
        dst.mkdir(exist_ok=True)
        for stale in ('kernels.vectorization.txt', 'strict.vectorization.txt'):
            (dst/stale).unlink(missing_ok=True)
        target = ['-march=native'] if 'native' in variant else ['-march=x86-64', '-mtune=generic']
        novec = ['-fno-vectorize', '-fno-slp-vectorize'] if clang else ['-fno-tree-loop-vectorize', '-fno-tree-slp-vectorize']
        vector = ['-Rpass=loop-vectorize', '-Rpass-missed=loop-vectorize', '-Rpass-analysis=loop-vectorize'] if clang else [f'-fopt-info-vec-all={dst / "kernels.vectorization.txt"}']
        # All primary kernels share relaxed reassociation. FMA contraction is
        # off for every variant so it is not a hidden extra advantage.
        kernel_flags = common + target + ['-O3', '-ffast-math', '-ffp-contract=off']
        if variant.startswith('scalar'):
            kernel_flags += novec
        else:
            kernel_flags += vector
        command(kernel_flags + ['-c', str(ROOT/'src/kernels.cpp'), '-o', str(dst/'kernels.o')], dst/'compile-kernels.log')
        strict_flags = common + target + ['-O3', '-fno-fast-math', '-ffp-contract=off']
        if variant.startswith('scalar'):
            strict_flags += novec
        elif clang:
            strict_flags += vector
        else:
            strict_flags += [f'-fopt-info-vec-all={dst / "strict.vectorization.txt"}']
        command(strict_flags + ['-c', str(ROOT/'src/strict_dot.cpp'), '-o', str(dst/'strict_dot.o')], dst/'compile-strict.log')
        command(common + ['-O2', '-march=x86-64', f'-DBUILD_VARIANT="{variant}"', '-c', str(ROOT/'src/benchmark.cpp'), '-o', str(dst/'benchmark.o')], dst/'compile-harness.log')
        command(common + [str(dst/f'{name}.o') for name in ('benchmark','kernels','strict_dot')] + ['-o',str(dst/'benchmark')])
        if shutil.which('objdump'):
            for name in ('kernels', 'strict_dot'):
                (dst/f'{name}.disasm.txt').write_text(run(['objdump','-d','-C','-M','intel',str(dst/f'{name}.o')]))
        # Compiler-detected feature macros, not assumed from a processor name.
        macros = subprocess.run([cxx]+target+['-dM','-E','-x','c++','-'], input='', text=True, capture_output=True, check=True).stdout
        (dst/'target_macros.txt').write_text(macros)
    metadata = dict(timestamp_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), compiler=version,
                    cxx=cxx, sanitizer=sanitize, commands=commands)
    (out/'build.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print(f'Built {", ".join(VARIANTS)} in {out}')

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cxx',default='g++')
    p.add_argument('--out',type=pathlib.Path,default=ROOT/'build')
    p.add_argument('--sanitize',action='store_true',help='diagnostics only; do not benchmark these binaries')
    a=p.parse_args()
    build(a.cxx,a.out.resolve(),a.sanitize)
