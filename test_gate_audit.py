"""Regression fixtures are archived REAL responses, never a new live approval."""
import copy,datetime as dt,json,unittest
from pathlib import Path
from gate_xauusd_cfd_audit import audit,PERIODS,scheduled_closed
from indicators import calculate
from abc_strategy import decide
FIXTURES=Path(__file__).parent/'tests/fixtures'
RAW=json.loads((FIXTURES/'real_gate_snapshot.json').read_text())
REPORT=json.loads((FIXTURES/'real_gate_audit.json').read_text())
NOW=int(dt.datetime.fromisoformat(REPORT['audited_at_utc']).timestamp())

class AuditRegressionTests(unittest.TestCase):
    def test_archived_real_snapshot_regression(self):
        result=audit(RAW,now=NOW)
        self.assertEqual(result['status'],'PASS',result['issues'])
        self.assertFalse(result['approved_for_executable_signal'])
        self.assertFalse(result['market_data']['ticker']['tick_timestamp_available'])
        self.assertGreater(result['cross_timeframe']['15m->4h']['matched'],20)
    def test_duplicate_is_blocked(self):
        raw=copy.deepcopy(RAW);raw['1h']['data']['list'].append(raw['1h']['data']['list'][-1])
        self.assertEqual(audit(raw,NOW)['status'],'FAIL')
    def test_unscheduled_missing_bar_is_blocked(self):
        raw=copy.deepcopy(RAW);del raw['15m']['data']['list'][-8]
        self.assertTrue(any('unexplained gap' in x for x in audit(raw,NOW)['issues']))
    def test_invalid_ohlc_blocked(self):
        raw=copy.deepcopy(RAW);raw['4h']['data']['list'][-3]['h']='1'
        self.assertEqual(audit(raw,NOW)['status'],'FAIL')
    def test_fresh_server_cannot_cover_stale_market(self):
        raw=copy.deepcopy(RAW);raw['1m']['data']['list']=raw['1m']['data']['list'][:-10]
        self.assertTrue(any('actual latest market bar stale' in x for x in audit(raw,NOW)['issues']))
    def test_no_http_provenance_blocked(self):
        raw=copy.deepcopy(RAW);raw.pop('_transport')
        self.assertEqual(audit(raw,NOW)['status'],'FAIL')
    def test_native_conflict_blocked(self):
        raw=copy.deepcopy(RAW);raw['1h']['data']['list'][-5]['c']=str(float(raw['1h']['data']['list'][-5]['c'])+.05)
        self.assertEqual(audit(raw,NOW)['status'],'FAIL')
    def test_data_fail_cannot_generate_signal(self):
        d=decide(RAW,{'status':'FAIL'},NOW)
        self.assertFalse(d['signal']);self.assertTrue(all(x['status']=='DATA_BLOCKED' for x in d['plans'].values()))
    def test_broad_spread_only_blocks_simulation(self):
        raw=copy.deepcopy(RAW);raw['ticker']['data']['ask_price']=str(float(raw['ticker']['data']['bid_price'])+1)
        result=audit(raw,NOW)
        self.assertEqual(result['status'],'PASS');self.assertFalse(result['approved_for_simulation'])
    def test_replay_signal_requires_macro_calendar(self):
        result=decide(RAW,REPORT,NOW)
        self.assertFalse(result['macro_gate']['passed']);self.assertFalse(result['signal'])
    def test_dst_session_gap(self):
        ts=lambda s:int(dt.datetime.fromisoformat(s).timestamp())
        self.assertTrue(scheduled_closed(ts('2026-10-29T21:30:00+00:00')))
        self.assertTrue(scheduled_closed(ts('2026-11-02T22:30:00+00:00')))
        self.assertFalse(scheduled_closed(ts('2026-11-03T10:30:00+00:00')))
    def test_prefix_causality(self):
        rows=[dict(t=x['t'],**{k:float(x[k]) for k in ('o','h','l','c')}) for x in RAW['1h']['data']['list']]
        full,_=calculate(rows,3600)
        for n in (5,14,30,60,100,len(rows)-1):
            part,_=calculate(rows[:n],3600)
            self.assertEqual(full[:n],part)
    def test_pivot_known_only_after_two_right_bars(self):
        rows=[dict(t=1800000000+i*3600,o=h-1,h=h,l=h-2,c=h-1) for i,h in enumerate([3,4,8,5,4])]
        before,_=calculate(rows[:4],3600);after,_=calculate(rows,3600)
        self.assertIsNone(before[-1]['swing_high']);self.assertEqual(after[-1]['swing_high']['price'],8)
        self.assertEqual(after[-1]['swing_high']['confirmed_at'],rows[-1]['t']+3600)
    def test_ema_independent_weighted_formula(self):
        rows=[dict(t=1800000000+i*3600,o=i+10,h=i+11,l=i+9,c=i+10) for i in range(60)]
        result,_=calculate(rows,3600);alpha=2/21;prices=[x['c'] for x in rows]
        expected=prices[0]*(1-alpha)**59+sum(alpha*prices[k]*(1-alpha)**(59-k) for k in range(1,60))
        self.assertAlmostEqual(result[-1]['ema20'],expected,10)
        atr=2.0
        for i in range(1,60):atr=atr+(max(2,abs(rows[i]['h']-prices[i-1]),abs(rows[i]['l']-prices[i-1]))-atr)/14
        self.assertAlmostEqual(result[-1]['atr14'],atr,10)
    def test_known_bos_then_choch(self):
        closes=[10,11,14,12,11,10,9,8,10,11,10,11,10,11,16,15,14,13,12,11,10,9,8,7,6]
        rows=[]
        for i,c in enumerate(closes):
            o=c-1.2 if not i or c>closes[i-1] else c+1.2
            rows.append(dict(t=1800000000+3600*i,o=o,c=c,h=max(o,c)+.1,l=min(o,c)-.1))
        bars,events=calculate(rows,3600)
        self.assertEqual([(e['kind'],e['direction']) for e in events],[('BOS','up'),('CHoCH','down')])
        self.assertAlmostEqual(events[0]['level'],14.1)
        self.assertAlmostEqual(events[1]['level'],7.9)
        self.assertEqual(events[0]['t'],rows[14]['t']+3600)
        self.assertEqual(events[1]['t'],rows[23]['t']+3600)

if __name__=='__main__':unittest.main()
