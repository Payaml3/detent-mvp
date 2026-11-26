import json,sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from marks import mark
K=sys.argv[1]; OUT=sys.argv[2]; os.makedirs(OUT,exist_ok=True)
W=json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'words.json')))[K]
G,P,OR='#18191B','#F3F3F1','#FF4A1F'
def wr(name,s): open(f'{OUT}/{name}','w').write(s+'\n')
hdr='<svg xmlns="http://www.w3.org/2000/svg"'
title='<title>DekernAI</title>'
# marks
for n,ink,o in [('mark','#18191B',OR),('mark-reverse',P,OR),('mark-mono-black','#000',"#000"),('mark-mono-white','#fff','#fff')]:
    wr(f'{n}.svg',f'{hdr} viewBox="0 0 48 48" role="img" aria-label="DekernAI">{title}{mark(K,ink,o)}</svg>')
wr('mark-currentcolor.svg',f'{hdr} viewBox="0 0 48 48" aria-hidden="true">{mark(K,"currentColor",OR)}</svg>')
# wordmark only
cap=W['cap']; tw=W['w']
import re
def bbox(d):
    nums=[float(x) for x in re.findall(r'-?\d+\.?\d*',d)]
    xs=nums[0::2]; ys=nums[1::2]; return min(xs),min(ys),max(xs),max(ys)
x0,y0,x1,y1=W['bb']
for n,ink in [('wordmark',G),('wordmark-reverse',P)]:
    wr(f'{n}.svg',f'{hdr} viewBox="{x0:.1f} {-cap:.1f} {x1-x0:.1f} {cap:.1f}" role="img" aria-label="DekernAI">{title}<path fill="{ink}" d="{W["d"]}"/></svg>')
# horizontal lockup: mark height = 1.42 cap, gap .36 mark
M=cap*1.42; sc=M/48; gap=M*0.27; my=-cap/2-M/2; total=M+gap+(x1-x0)
for n,ink in [('lockup-horizontal',G),('lockup-horizontal-reverse',P)]:
    wr(f'{n}.svg',f'{hdr} viewBox="0 {my:.2f} {total:.2f} {M:.2f}" role="img" aria-label="DekernAI">{title}<g transform="translate(0 {my:.2f}) scale({sc:.4f})">{mark(K,ink,OR)}</g><path fill="{ink}" transform="translate({M+gap-x0:.2f} 0)" d="{W["d"]}"/></svg>')
# stacked lockup
M2=cap*2.6; sc2=M2/48; gap2=cap*0.7; Wd=x1-x0; total_w=max(Wd,M2); h=M2+gap2+cap
for n,ink in [('lockup-stacked',G),('lockup-stacked-reverse',P)]:
    wr(f'{n}.svg',f'{hdr} viewBox="0 0 {total_w:.2f} {h:.2f}" role="img" aria-label="DekernAI">{title}<g transform="translate({(total_w-M2)/2:.2f} 0) scale({sc2:.4f})">{mark(K,ink,OR)}</g><path fill="{ink}" transform="translate({(total_w-Wd)/2-x0:.2f} {h:.2f})" d="{W["d"]}"/></svg>')
# favicon: adapts to light/dark tab bars
fav=(f'{hdr} viewBox="0 0 48 48"><style>.i{{fill:{G}}}@media (prefers-color-scheme:dark){{.i{{fill:{P}}}}}</style>'
     + mark(K,'X',OR).replace('fill="X"','class="i"') + '</svg>')
wr('favicon.svg',fav)
# app icon: graphite tile, paper mark
wr('app-icon.svg',f'{hdr} viewBox="0 0 48 48"><rect width="48" height="48" fill="{G}"/><g transform="translate(7.2 7.2) scale(0.7)">{mark(K,P,OR)}</g></svg>')
wr('favicon-tile.svg',f'{hdr} viewBox="0 0 48 48"><rect width="48" height="48" rx="9" fill="{G}"/><g transform="translate(4.8 4.8) scale(0.8)">{mark(K,P,OR)}</g></svg>')
print('ok')
