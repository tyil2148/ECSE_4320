"""No disk benchmarks run in this unit suite. Integration checks are separate."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from ssdbench.analysis import analyze, choose_knee, interval_window_mean, parse_document, summarize_rows
from ssdbench.common import parse_size
from ssdbench.plan import Case, build_cases, fio_config
from ssdbench.runner import append_event, journal_events
from ssdbench.safety import allocate, cleanup, create_target, target_directory, validate_target


def stat(n, latency_ns, iops=None):
    return {"total_ios": n, "io_bytes": n*4096, "iops": iops or n, "bw_bytes": n*4096,
            "clat_ns": {"mean": latency_ns, "bins": {str(latency_ns): n}},
            "lat_ns": {"mean": latency_ns+100}, "slat_ns": {"mean":100}}


def case(**kwargs):
    base=Case("test","queue","random",100,4096,16,1,64*1024**2,10,0).dictionary()
    base.update(kwargs)
    base["total_qd"]=base["iodepth"]*base["numjobs"]
    return base


class MatrixTests(unittest.TestCase):
    def test_required_matrix(self):
        cases=build_cases(16*1024**3)
        self.assertEqual(len(cases),97)
        self.assertEqual(len({c.case_id for c in cases}),len(cases))
        self.assertEqual({c.bs//1024 for c in cases if c.family=="block"},{4,16,32,64,128,256})
        self.assertEqual(len([c for c in cases if c.family=="block"]),24)
        self.assertEqual({c.iodepth for c in cases if c.family=="queue"},{1,2,4,8,16,32,64,128,256})
        self.assertEqual({c.read_pct for c in cases if c.family=="mix"},{0,50,70,100})
        for c in cases:
            self.assertEqual(c.working_set % (c.bs*c.numjobs),0)
        parallel=[c for c in cases if c.family=="parallel"]
        self.assertEqual({c.total_qd for c in parallel},{16,64})
        self.assertEqual({c.working_set for c in parallel},{16*1024**3})

    def test_fio_bounds_and_buffered_control(self):
        for c in build_cases(64*1024**2):
            config=fio_config(c,"/tmp/owned/workload.bin",123)
            self.assertIn("allow_file_create=0",config)
            self.assertIn("gtod_reduce=0",config)
            self.assertIn("offset_increment="+str(c.working_set//c.numjobs),config)
            if c.family=="pitfall":
                self.assertEqual(c.engine,"psync")
                self.assertEqual(c.iodepth,1)
        c=build_cases(64*1024**2)[0]
        with self.assertRaises(ValueError): fio_config(c,"/tmp/x\nrw=write",1)

    def test_sizes(self):
        self.assertEqual(parse_size("16GiB"),16*1024**3)
        for s in ("1.5GiB","16GB","-1","NaN"):
            with self.assertRaises(ValueError): parse_size(s)
        with self.assertRaises(ValueError): build_cases(63*1024**2)


class AnalysisTests(unittest.TestCase):
    def test_state_windows_do_not_give_queue_drain_a_full_interval_weight(self):
        values=[{"time_s":t,"value":v} for t,v in ((1,10),(2,20),(3,30),(3.002,10000))]
        self.assertEqual(interval_window_mean(values,0,1),10)
        self.assertEqual(interval_window_mean(values,2,3),30)
        self.assertAlmostEqual(interval_window_mean(values,.5,1.5),15)

    def test_modified_raw_is_excluded_and_subset_is_not_full_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td); (p/"raw").mkdir(); (p/"logs").mkdir()
            c=case()
            (p/"manifest.json").write_text(json.dumps({"parameters":{"size":64*1024**2,"trials":2,"families":["queue"],"profile":"full"}}))
            (p/"plan.json").write_text(json.dumps({"cases":[c]}))
            (p/"raw"/"run.json").write_text(json.dumps({"jobs":[{"error":0,"read":stat(100,1000)}]}))
            append_event(p,{"phase":"measured","status":"complete","case":c,"trial":1,"run_id":"run","raw":"raw/run.json","raw_sha256":"deliberately wrong"})
            coverage=analyze(p)
            self.assertEqual(coverage["valid_runs"],0)
            self.assertEqual(len(coverage["missing_runs"]),2)
            self.assertFalse(coverage["all_selected_runs_complete"])
            self.assertFalse(coverage["full_default_setting_matrix_with_repeats"])
            self.assertIn("invalid_result",(p/"analysis"/"issues.csv").read_text())

    def test_weighted_mean_and_pooled_quantile(self):
        # The 99th percentile must come from merged counts, not averaged quantiles.
        doc={"jobs":[{"error":0,"read":stat(9900,1000)}, {"error":0,"read":stat(100,1000000)}]}
        rows,hist,_,_=parse_document(doc,case(numjobs=2),"run",1)
        total=next(r for r in rows if r["direction"]=="total")
        self.assertAlmostEqual(total["mean_clat_us"],10.99)
        self.assertEqual(total["p99_us"],1)
        self.assertEqual(total["p999_us"],1000)
        self.assertEqual(sum(r["count"] for r in hist if r["direction"]=="total"),10000)
        self.assertAlmostEqual(total["little_l_clat"],.1099)

    def test_mixed_direction_aggregation(self):
        doc={"jobs":[{"error":0,"read":stat(700,1000),"write":stat(300,2000)}]}
        rows,_,_,_=parse_document(doc,case(read_pct=70),"run",1)
        total=next(r for r in rows if r["direction"]=="total")
        self.assertEqual(total["achieved_read_pct"],70)
        self.assertAlmostEqual(total["mean_clat_us"],1.3)
        self.assertEqual(total["p95_us"],2)

    def test_reject_job_error_missing_bins_and_counts(self):
        for doc,c in [({"jobs":[{"error":5,"read":stat(10,1000)}]},case()),
                      ({"jobs":[{"error":0,"read":stat(10,1000)}]},case(numjobs=2))]:
            with self.assertRaises(ValueError): parse_document(doc,c,"run",1)
        d={"jobs":[{"error":0,"read":stat(10,1000)}]}
        d["jobs"][0]["read"]["clat_ns"]["bins"]["1000"]=9
        with self.assertRaises(ValueError): parse_document(d,case(),"run",1)
        d={"jobs":[{"error":0,"read":stat(10,1000)}, {"error":0,"read":stat(10,2000)}]}
        for j in d["jobs"]: j["read"]["clat_ns"].pop("bins")
        with self.assertRaises(ValueError): parse_document(d,case(numjobs=2),"run",1)

    def test_unit_conversion_and_sample_sd(self):
        a={"jobs":[{"error":0,"read":stat(100,1000)}]}
        b=copy.deepcopy(a)
        b["jobs"][0]["read"]["iops"]=300
        r1=parse_document(a,case(),"r1",1)[0]
        r2=parse_document(b,case(),"r2",2)[0]
        total=next(r for r in summarize_rows(r1+r2) if r["direction"]=="total")
        self.assertEqual(total["iops_mean"],200)
        self.assertAlmostEqual(total["iops_sd"],200**.5*10)
        self.assertEqual(total["n"],2)
        self.assertAlmostEqual(total["mib_s_mean"],100*4096/1024**2)

    def test_knee_and_no_plateau(self):
        curve=[{"iodepth":q,"mib_s_median":bw,"mean_lat_us_median":lat} for q,bw,lat in [(1,10,10),(2,20,10),(4,38,10),(8,40,20),(16,40,40)]]
        self.assertEqual(choose_knee(curve)["selected_qd"],4)
        self.assertTrue(choose_knee(curve)["plateau_observed"])
        no=[{"iodepth":q,"mib_s_median":q*10,"mean_lat_us_median":10} for q in (1,2,4)]
        self.assertFalse(choose_knee(no)["plateau_observed"])
        self.assertEqual(choose_knee(no)["selected_qd"],4)


class SafetyTests(unittest.TestCase):
    def test_refuses_unowned_existing_files(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"data"; p.mkdir(); (p/"important.txt").write_text("keep")
            with self.assertRaises(ValueError): create_target(p,64*1024**2)
            self.assertEqual((p/"important.txt").read_text(),"keep")

    def test_identity_size_symlinks_and_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"data"; create_target(p,64*1024**2); allocate(p,64*1024**2)
            with self.assertRaises(ValueError): validate_target(p)
            self.assertFalse(validate_target(p,False)["initialized"])
            (p/"workload.bin").write_bytes(b"changed")
            with self.assertRaises(ValueError): validate_target(p,False)
            link=Path(td)/"link"; link.symlink_to(p,target_is_directory=True)
            with self.assertRaises(ValueError): target_directory(link)

    def test_cleanup_is_not_recursive(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"data"; create_target(p,64*1024**2); allocate(p,64*1024**2)
            (p/"keep.txt").write_text("keep")
            cleanup(p)
            self.assertEqual((p/"keep.txt").read_text(),"keep")
            self.assertFalse((p/"workload.bin").exists())

    def test_hardlink_and_replaced_file_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"data"; create_target(p,64*1024**2); allocate(p,64*1024**2)
            link=Path(td)/"hardlink"; os.link(p/"workload.bin",link)
            with self.assertRaises(ValueError): validate_target(p,False)
            link.unlink()
            original=p/"workload.bin"; original.rename(p/"original.bin")
            with original.open("wb") as f: f.truncate(64*1024**2)
            with self.assertRaises(ValueError): validate_target(p,False)

    def test_crash_truncated_journal_is_retained_and_repaired(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            append_event(p,{"status":"complete","value":1})
            with (p/"journal.jsonl").open("ab") as f: f.write(b'{"status": "star')
            self.assertEqual(len(journal_events(p)),1)
            append_event(p,{"status":"complete","value":2})
            self.assertEqual([x["value"] for x in journal_events(p)],[1,2])
            self.assertEqual(len(list(p.glob("journal_fragment_*.txt"))),1)


if __name__=="__main__": unittest.main()
