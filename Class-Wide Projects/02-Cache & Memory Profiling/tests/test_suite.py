#!/usr/bin/env python3
"""Small correctness and pipeline checks, not performance validation."""
import importlib.util, json, os, subprocess, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
run=module('run');analyze=module('analyze')
class BenchTests(unittest.TestCase):
    def invoke(self,**kwargs):
        args=[str(ROOT/'build/membench'),'--cpu',str(min(os.sched_getaffinity(0))),'--ms','5']
        for k,v in kwargs.items():args += ['--'+k,str(v)]
        p=subprocess.run(args,capture_output=True,text=True,check=True);return json.loads(p.stdout)
    def test_cpp_correctness(self):self.assertEqual(self.invoke(mode='selftest')['status'],'ok')
    def test_chase_and_stream_accounting(self):
        c=self.invoke(mode='chase',bytes=65536,stride=64,pattern='random',counters=0)
        self.assertEqual(c['nodes'],1024);self.assertAlmostEqual(c['latency_ns'],c['elapsed_ns']/c['operations'],places=8)
        for read in [0,50,70,100]:
            s=self.invoke(mode='stream',bytes=65536,stride=256,granularity=64,read_pct=read,counters=0)
            self.assertEqual(s['useful_bytes'],s['operations']*64)
            self.assertLessEqual(abs(s['actual_read_fraction']-read/100),0.03)
    def test_loaded_workers(self):
        cpus=sorted(os.sched_getaffinity(0))
        if len(cpus)<2:self.skipTest('two CPUs required')
        c=self.invoke(mode='loaded',bytes=262144,probe_bytes=262144,load_cpus=str(cpus[1]),read_pct=70)
        self.assertEqual(c['load_threads'],1);self.assertGreater(c['load_useful_bytes'],0);self.assertGreater(c['latency_ns'],0)
    def test_plan_coverage_and_sparse_dram(self):
        jobs,settings=run.plan('full',[],list(range(12)))
        self.assertEqual({j['read_pct'] for j in jobs if j['experiment']=='pattern_mix'},{0,50,70,100})
        self.assertEqual(len([j for j in jobs if j['experiment']=='pattern_mix']),48)
        for j in jobs:
            if j['experiment']=='pattern_mix':self.assertEqual(j['bytes']//j['stride']*64,settings['dram_line_footprint_bytes'])
        self.assertEqual({j['pages'] for j in jobs if j['experiment']=='tlb'},{'base','thp','hugetlb'})
        self.assertIn(11,{j['load_threads_requested'] for j in jobs if j['experiment']=='loaded'})
    def test_statistics_and_missing_counter_rules(self):
        rows=[dict(status='ok',experiment='baseline',operations=1000,latency_ns=n,cycles_status='not_supported') for n in [10,20,30]]
        s=analyze.summarize(rows)[0];self.assertEqual(s['latency_ns_mean'],20);self.assertEqual(s['latency_ns_sd'],10);self.assertNotIn('cycles_per_operation_mean',s)
        low=analyze.derive(dict(operations=100,cycles_status='ok',cycles_scaled=1000,cycles_running_fraction=.2))
        self.assertNotIn('cycles_per_operation',low)
    def test_runner_analysis_smoke(self):
        with tempfile.TemporaryDirectory() as t:
            out=Path(t)/'run'
            subprocess.run(['python3',str(ROOT/'scripts/run.py'),'--profile','smoke','--out',str(out),'--trials','1','--ms','5','--experiments','baseline,loaded'],check=True,stdout=subprocess.DEVNULL)
            subprocess.run(['python3',str(ROOT/'scripts/analyze.py'),str(out),'--no-plots'],check=True,stdout=subprocess.DEVNULL)
            self.assertTrue((out/'processed/summary.csv').is_file());self.assertTrue(json.loads((out/'processed/audit.json').read_text())['smoke_data_present'])
if __name__=='__main__':unittest.main(verbosity=2)
