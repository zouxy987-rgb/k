"""Causal OHLC indicators. All input bars MUST already be closed."""
from copy import deepcopy


def calculate(rows, seconds):
    bars = deepcopy(rows)
    ema20 = ema50 = atr = None
    hi = lo = None
    trend = 'unknown'
    broken = set()
    events = []
    for i, b in enumerate(bars):
        b['end'] = b['t'] + seconds
        b['after_gap'] = i > 0 and b['t'] != bars[i-1]['t'] + seconds
        previous = bars[i-1]['c'] if i else b['c']
        tr = max(b['h']-b['l'], abs(b['h']-previous), abs(b['l']-previous))
        ema20 = b['c'] if ema20 is None else ema20 + 2/21*(b['c']-ema20)
        ema50 = b['c'] if ema50 is None else ema50 + 2/51*(b['c']-ema50)
        atr = tr if atr is None else atr + (tr-atr)/14
        b.update(ema20=ema20 if i>=19 else None, ema50=ema50 if i>=49 else None,
                 atr14=atr if i>=13 else None, prev_hi=hi, prev_lo=lo,
                 body_ratio=abs(b['c']-b['o'])/(b['h']-b['l']) if b['h']>b['l'] else 0,
                 bos=None, choch=None, structure_before=trend)
        # Compare ONLY with pivots confirmed before this bar; each pivot breaks once.
        if i and i>=13 and not b['after_gap']:
            for direction, pivot in [('up', hi), ('down', lo)]:
                if pivot is None or (direction,pivot['t']) in broken:
                    continue
                level = pivot['price'] + (1 if direction=='up' else -1)*.1*atr
                cross = (b['c']>level and previous<=level) if direction=='up' else (b['c']<level and previous>=level)
                if cross and b['body_ratio']>=.5:
                    b['bos'] = direction
                    if trend in ('up','down') and trend!=direction and (direction!='up' or b['body_ratio']>=.55):
                        b['choch'] = direction
                    events.append({'t':b['end'],'direction':direction,'kind':'CHoCH' if b['choch'] else 'BOS','level':pivot['price']})
                    trend=direction
                    broken.add((direction,pivot['t']))
        # Five-bar strict pivots become visible after the right two bars close.
        if i>=4:
            j=i-2
            center=bars[j]
            neighbors=[bars[k] for k in (j-2,j-1,j+1,j+2)]
            if all(center['h']>x['h'] for x in neighbors):
                hi={'price':center['h'],'t':center['t'],'confirmed_at':b['end']}
            if all(center['l']<x['l'] for x in neighbors):
                lo={'price':center['l'],'t':center['t'],'confirmed_at':b['end']}
        b.update(swing_high=hi,swing_low=lo,structure=trend)
    return bars, events
