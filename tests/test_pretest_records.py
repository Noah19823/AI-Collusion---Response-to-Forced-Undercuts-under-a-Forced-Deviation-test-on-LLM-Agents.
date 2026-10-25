"""Raw-pretest admission regressions; synthetic fixtures, no provider calls."""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collusion.runner import base_episode, digest, verify_pretest_records


class FixedSolo:
    async def choose(self,prompt,agent):
        return ({"chosen_price":1.8,"plans":"Synthetic fixture",
                 "insights":"Synthetic fixture","observations":""},
                {"provider":"mock","model":"synthetic-monopoly-fixture"})


class PretestRecordsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch("collusion.runner.LOGROOT",Path(self.temp.name)):
            self.path=asyncio.run(base_episode(FixedSolo(),"mock",
                "synthetic-monopoly-fixture",50,mono=True))
        self.meta=json.loads((self.path/"meta.json").read_text())
        self.done=json.loads((self.path/"completion.json").read_text())
        self.raw=(self.path/"rounds.jsonl").read_bytes()

    def rewrite_fixture(self,mutate):
        rows=[json.loads(x) for x in self.raw.splitlines()]
        mutate(rows)
        raw=b"".join(json.dumps(r).encode()+b"\n" for r in rows)
        (self.path/"rounds.jsonl").write_bytes(raw)
        self.done["rounds_sha256"]=digest(raw)

    def check(self):
        verify_pretest_records(self.path,self.meta,self.done)

    def test_valid_seal_is_read_only(self):
        before={p.name:p.read_bytes() for p in self.path.iterdir()}
        self.check()
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.path.iterdir()})

    def test_summary_without_rounds_cannot_admit(self):
        (self.path/"rounds.jsonl").unlink()
        with self.assertRaises(OSError):self.check()

    def test_corrupt_rounds_fail_before_summary(self):
        (self.path/"rounds.jsonl").write_bytes(self.raw+b"\n")
        with self.assertRaisesRegex(ValueError,"checksum"):self.check()

    def test_cli_rejects_missing_rounds_before_constructing_provider(self):
        from collusion.runner import main
        self.meta["provider"]="anthropic"
        (self.path/"meta.json").write_text(json.dumps(self.meta))
        (self.path/"rounds.jsonl").unlink()
        argv=["runner","base","--provider","anthropic","--model",self.meta["model"],
              "--execute-paid","--pretest-dir",str(self.path),
              "--max-http-attempts","10","--deadline-seconds","600"]
        with patch.object(sys,"argv",argv),patch("collusion.runner.get_client") as client:
            with self.assertRaises(SystemExit) as caught:main()
        self.assertEqual(caught.exception.code,2)
        client.assert_not_called()

    def test_tiny_libm_roundoff_is_not_rejected(self):
        def alter(rows):rows[3]["actors"]["Firm A"]["profit"]+=1e-12
        self.rewrite_fixture(alter)
        self.check()

    def test_incomplete_resealed_rounds_are_rejected(self):
        self.rewrite_fixture(lambda rows:rows.pop())
        with self.assertRaisesRegex(ValueError,"all planned"):self.check()

    def test_resealed_wrong_history_is_rejected(self):
        self.rewrite_fixture(lambda rows:rows[3]["actors"]["Firm A"].update(prompt="wrong history"))
        with self.assertRaisesRegex(ValueError,"prompt/history"):self.check()

    def test_resealed_wrong_profit_is_rejected(self):
        self.rewrite_fixture(lambda rows:rows[3]["actors"]["Firm A"].update(profit=999))
        with self.assertRaisesRegex(ValueError,"market outcomes"):self.check()

    def test_summary_cannot_override_primitive_mean(self):
        self.done["last10_mean"]={"Firm A":1.81}
        with self.assertRaisesRegex(ValueError,"summary"):self.check()

    def test_wrong_recorded_model_is_rejected(self):
        def alter(rows):rows[3]["actors"]["Firm A"]["model_meta"]["model"]="other-model"
        self.rewrite_fixture(alter)
        with self.assertRaisesRegex(ValueError,"provider/model"):self.check()

    def test_optimistic_pass_flag_does_not_override_actual_prices(self):
        from collusion.runner import recalculate_round
        from collusion.market import Market
        from collusion.prompt import build_prompt
        rows=[]
        for line in self.raw.splitlines():
            row=json.loads(line);actor=row["actors"]["Firm A"]
            actor["executed_price"]=actor["model_chosen_price"]=1.3
            actor["response"]["chosen_price"]=1.3
            actor["prompt"]=build_prompt(rows,"Firm A")
            actor["prompt_sha256"]=digest(actor["prompt"].encode())
            recalculate_round(row,Market());rows.append(row)
        raw=b"".join(json.dumps(r).encode()+b"\n" for r in rows)
        (self.path/"rounds.jsonl").write_bytes(raw)
        self.done.update(rounds_sha256=digest(raw),last10_mean={"Firm A":1.3},
                         final_prices={"Firm A":1.3},pretest_near_one_product_monopoly=True)
        with self.assertRaisesRegex(ValueError,"monopoly criterion"):self.check()

if __name__=="__main__":unittest.main()
