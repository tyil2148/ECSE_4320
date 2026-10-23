#!/usr/bin/env python3
"""Check operation counts, cache traffic and experiment isolation analytically."""
import pathlib, sys, unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'scripts'))
from analyze import traffic, bootstrap_ratio
from run_experiments import cases
import random
class Analysis(unittest.TestCase):
    def test_operation_and_byte_counts(self):
        self.assertEqual(traffic('mul',100,1,4),(1200,100,1200,1600))
        self.assertEqual(traffic('bandwidth',100,1,4),(800,100,800,1200))
        self.assertEqual(traffic('dot',100,1,8),(1600,200,1600,1600))
        self.assertEqual(traffic('saxpy',100,1,4),(800,200,1200,1200))
        self.assertEqual(traffic('stencil',100,1,8),(1616,500,3200,2416))
        self.assertEqual(traffic('mul',100,8,8)[3],4*100*64)
    def test_bootstrap_known_ratio(self):
        self.assertEqual(bootstrap_ratio([2]*7,[1]*7,random.Random(1),50),(2,2))
    def test_orthogonal_stride_sweeps(self):
        plan=cases('full',64)
        for dtype in ('f32','f64'):
            rows=[c for c in plan if c['study']=='stride_fixed_footprint' and c['dtype']==dtype]
            bases=set(c['n']*c['stride'] for c in rows)
            for base in bases:self.assertEqual({c['stride'] for c in rows if c['n']*c['stride']==base},{1,2,4,8})
        self.assertTrue(any(c['study']=='tail' and c['n']%8!=0 for c in plan))
    def test_all_assignment_kernels_and_types(self):
        plan=cases('full',64)
        for k in ('saxpy','dot','mul','stencil'):
            for d in ('f32','f64'):
                self.assertGreaterEqual(len([c for c in plan if c['kernel']==k and c['dtype']==d and c['study']=='locality']),10)
if __name__=='__main__':unittest.main()
