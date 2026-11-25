"""The stylesheet of a published site. One file per site (shared base + the template's own layout rules), served with a content-hashed name so it can be cached for a year.

Design: calm and premium. System fonts only (nothing is downloaded), large tight headings, generous space, rounded media and cards with soft shadows, alternating quiet backgrounds, one accent
colour from a whitelist, motion only where it helps (a focus ring, a pressed button, a card lift that respects reduced motion). No gradients and no decorative shapes. There is no inline style anywhere in the pages (the Content-Security-Policy forbids it), so every
variation, including the accent, is a class defined here."""
from app.services.sites.catalog import ACCENTS

BASE = """
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth;scroll-padding-top:4.5rem}
body{margin:0;font:400 1rem/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;color:var(--ink);background:var(--bg);-webkit-font-smoothing:antialiased}
:root{--ink:#111;--mute:#55575d;--rule:#d9dadd;--bg:#fff;--soft:#f4f4f2;--a:#111;--maxw:72rem;--pad:clamp(1.1rem,4vw,2.5rem)}
"""
BASE += "".join(f".a-{k}{{--a:{v}}}\n" for k, v in ACCENTS.items())
BASE += """
img{display:block;max-width:100%;height:auto}
a{color:inherit}
h1,h2,h3{font-weight:700;line-height:1.08;letter-spacing:-.02em;margin:0}
h1{font-size:clamp(2.4rem,7vw,4.6rem)}
h2{font-size:clamp(1.7rem,4vw,2.6rem)}
h3{font-size:1.15rem;letter-spacing:-.01em;line-height:1.25}
p{margin:0 0 1em}
.wrap{max-width:var(--maxw);margin:0 auto;padding:0 var(--pad)}
.skip{position:absolute;left:-999px;top:0;background:var(--ink);color:#fff;padding:.7rem 1rem;z-index:50}
.skip:focus{left:0}
:focus-visible{outline:3px solid var(--a);outline-offset:3px}
.hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}
.eyebrow{font-size:.78rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--a);margin:0 0 1rem}
.lead{font-size:clamp(1.05rem,2vw,1.3rem);color:var(--mute);max-width:40rem}
.btn{display:inline-flex;align-items:center;justify-content:center;min-height:3rem;padding:.7rem 1.4rem;border:2px solid var(--a);background:var(--a);color:#fff;font-weight:700;text-decoration:none;border-radius:2px;transition:transform .12s ease}
.btn:active{transform:translateY(1px)}
.btn.alt{background:transparent;color:var(--a)}
.btns{display:flex;flex-wrap:wrap;gap:.75rem;margin-top:1.75rem}
/* header and footer */
.top{position:sticky;top:0;z-index:20;background:var(--bg);border-bottom:1px solid var(--rule)}
.top .wrap{display:flex;align-items:center;gap:1.25rem;min-height:3.75rem}
.brand{font-weight:800;letter-spacing:-.02em;text-decoration:none;font-size:1.1rem;display:flex;align-items:center;gap:.6rem;white-space:nowrap}
.brand img{height:2rem;width:auto}
.nav{display:flex;gap:1.1rem;overflow-x:auto;flex:1;scrollbar-width:none;font-size:.92rem}
.nav::-webkit-scrollbar{display:none}
.nav a{text-decoration:none;color:var(--mute);white-space:nowrap;padding:.4rem 0}
.nav a:hover{color:var(--ink)}
.top .btn{min-height:2.5rem;padding:.4rem 1rem;font-size:.92rem}
.foot{border-top:1px solid var(--rule);margin-top:0;padding:2.5rem 0 5.5rem;font-size:.92rem;color:var(--mute)}
.foot .wrap{display:grid;gap:1.25rem;grid-template-columns:repeat(auto-fit,minmax(14rem,1fr))}
.foot strong{color:var(--ink)}
.foot ul{list-style:none;margin:0;padding:0}
.foot li{margin:.25rem 0}
.sticky{position:fixed;left:0;right:0;bottom:0;z-index:30;display:none;gap:.5rem;padding:.6rem var(--pad);background:var(--bg);border-top:1px solid var(--rule)}
.sticky .btn{flex:1;min-height:2.9rem}
.pv{background:#111;color:#fff;font-size:.85rem;text-align:center;padding:.4rem}
/* sections */
section.s{padding:clamp(3rem,8vw,6rem) 0;border-top:1px solid var(--rule)}
section.s:first-of-type{border-top:0}
.sh{display:grid;gap:1rem;margin-bottom:2.25rem}
.sh p{color:var(--mute);max-width:40rem;margin:0}
.grid{display:grid;gap:1.5rem;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));list-style:none;margin:0;padding:0}
.card{border-top:2px solid var(--ink);padding-top:1rem}
.card p{color:var(--mute);margin:.5rem 0 0}
.card .price{font-weight:700;color:var(--ink);margin-top:.5rem}
.card img{margin-bottom:1rem;aspect-ratio:4/3;object-fit:cover;width:100%}
.rows{list-style:none;margin:0;padding:0}
.rows li{display:flex;justify-content:space-between;gap:1.5rem;padding:.85rem 0;border-bottom:1px solid var(--rule)}
.rows .note{display:block;color:var(--mute);font-size:.9rem}
.price{white-space:nowrap}
.cols{display:grid;gap:2.5rem;grid-template-columns:repeat(auto-fit,minmax(18rem,1fr))}
.hl{list-style:none;margin:1.25rem 0 0;padding:0;display:flex;flex-wrap:wrap;gap:.5rem}
.hl li,.chips li{border:1px solid var(--ink);padding:.3rem .8rem;font-size:.9rem}
.chips{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:.5rem}
.steps{counter-reset:s;list-style:none;margin:0;padding:0;display:grid;gap:1.5rem;grid-template-columns:repeat(auto-fit,minmax(14rem,1fr))}
.steps li{counter-increment:s;border-top:2px solid var(--ink);padding-top:1rem}
.steps li::before{content:counter(s,decimal-leading-zero);display:block;font-weight:800;color:var(--a);margin-bottom:.5rem}
.gal{display:grid;gap:.75rem;grid-template-columns:repeat(auto-fill,minmax(14rem,1fr));margin:0}
.gal figure{margin:0}
.gal img{width:100%;aspect-ratio:4/3;object-fit:cover}
.gal figcaption{font-size:.88rem;color:var(--mute);padding-top:.4rem}
details.faq{border-top:1px solid var(--rule);padding:1rem 0}
details.faq:last-child{border-bottom:1px solid var(--rule)}
details.faq summary{cursor:pointer;font-weight:700;list-style:none}
details.faq summary::-webkit-details-marker{display:none}
details.faq summary::after{content:"+";float:right;font-weight:400}
details.faq[open] summary::after{content:"\\2212"}
details.faq p{margin:.75rem 0 0;color:var(--mute)}
table.hrs{border-collapse:collapse;width:100%;max-width:26rem}
table.hrs th,table.hrs td{text-align:left;padding:.55rem 0;border-bottom:1px solid var(--rule);font-weight:400}
table.hrs th{font-weight:600}
.dis{font-size:.9rem;color:var(--mute);max-width:46rem}
.band{background:var(--a);color:#fff;padding:clamp(2.5rem,6vw,4rem) 0}
.band .btn{background:#fff;color:var(--a);border-color:#fff}
.vm{display:inline-block;width:.85rem;height:.85rem;border:2px solid;margin-right:.5rem;vertical-align:-1px;position:relative}
.vm::after{content:"";position:absolute;inset:2px;border-radius:50%;background:currentColor}
.vm-veg{color:#15803d}.vm-nonveg{color:#b91c1c}.vm-egg{color:#a16207}
.team{display:grid;gap:1.5rem;grid-template-columns:repeat(auto-fit,minmax(13rem,1fr));list-style:none;margin:0;padding:0}
.team img{aspect-ratio:1/1;object-fit:cover;width:100%;margin-bottom:.75rem}
.team .role{color:var(--a);font-weight:600;font-size:.9rem}
/* enquiry form */
form.enq{display:grid;gap:1rem;max-width:32rem}
form.enq label{display:grid;gap:.35rem;font-weight:600;font-size:.92rem}
form.enq input,form.enq textarea{font:inherit;padding:.75rem;border:1px solid var(--ink);border-radius:2px;background:#fff;color:var(--ink);width:100%}
form.enq .chk{display:flex;gap:.6rem;align-items:flex-start;font-weight:400}
form.enq .chk input{width:auto;margin-top:.3rem}
.small{font-size:.85rem;color:var(--mute)}
/* premium layer */
body{font-size:1.05rem}
h1{font-weight:800;letter-spacing:-.035em}
h2{letter-spacing:-.03em}
.wrap{--maxw:75rem}
.btn{border-radius:999px;padding:.8rem 1.6rem;box-shadow:0 6px 18px -8px rgba(0,0,0,.35)}
.btn.alt{box-shadow:none;border-color:var(--rule);color:var(--ink)}
.btn.alt:hover{border-color:var(--a)}
.top{background:rgba(255,255,255,.94);border-bottom-color:#ececec}
.top .wrap{min-height:4.5rem}
.brand{font-size:1.2rem}
section.s{border-top:0;padding:clamp(3.5rem,9vw,7rem) 0}
section.s:nth-of-type(even),section.s.tint{background:var(--soft)}
.sh h2{max-width:22ch}
.eyebrow{display:inline-block;border:1px solid var(--rule);border-radius:999px;padding:.35rem .9rem;letter-spacing:.12em}
.hero img.hi,.gal img,.card img,.team img,.cols img{border-radius:18px;box-shadow:0 24px 48px -28px rgba(0,0,0,.45)}
.grid .card,.svc .card{border:1px solid #e9e9e6;border-radius:18px;background:#fff;padding:1.5rem;box-shadow:0 1px 2px rgba(0,0,0,.04),0 18px 40px -32px rgba(0,0,0,.5);transition:transform .18s ease,box-shadow .18s ease}
.grid .card:hover{transform:translateY(-3px);box-shadow:0 26px 50px -30px rgba(0,0,0,.45)}
.card h3{font-size:1.2rem}
.card::before{content:"";display:block;width:2.25rem;height:3px;border-radius:3px;background:var(--a);margin-bottom:1rem}
.hl li,.chips li{border:1px solid var(--rule);border-radius:999px;background:#fff}
.gal{gap:1rem}
.gal figure:first-child{grid-column:span 2}
.gal figure:first-child img{aspect-ratio:16/10}
.rsum{display:flex;flex-wrap:wrap;align-items:center;gap:.75rem;margin:0 0 2rem;color:var(--mute)}
.rsum strong{font-size:2.6rem;line-height:1;color:var(--ink);letter-spacing:-.03em}
.stars{color:#f5a623;letter-spacing:.08em;font-size:1.05rem}
.revs{list-style:none;margin:0 0 1.25rem;padding:0;display:grid;gap:1.25rem;grid-template-columns:repeat(auto-fit,minmax(17rem,1fr))}
.rev{background:#fff;border:1px solid #e9e9e6;border-radius:18px;padding:1.5rem;box-shadow:0 18px 40px -32px rgba(0,0,0,.5)}
.rev p{margin:.75rem 0 0}
.rev .who{font-weight:700;margin-top:1rem}
.rev .who span{font-weight:400;color:var(--mute)}
form.enq{background:#fff;border:1px solid #e9e9e6;border-radius:22px;padding:clamp(1.25rem,3vw,2rem);box-shadow:0 30px 60px -40px rgba(0,0,0,.5)}
form.enq input,form.enq textarea{border:1px solid var(--rule);border-radius:12px}
.appt{border:1px solid #e9e9e6;border-radius:22px;background:#fff;box-shadow:0 30px 60px -40px rgba(0,0,0,.5)}
.band{border-radius:28px;margin:0 var(--pad) 3rem}
.foot{background:#0f1115;color:#b9bcc3;border-top:0;padding-top:3.5rem}
.foot strong{color:#fff}
.foot a{color:#e9eaee}
.sticky{box-shadow:0 -10px 30px -18px rgba(0,0,0,.35)}
@media (max-width:42rem){.gal figure:first-child{grid-column:auto}.band{margin:0 .75rem 2rem}}
@media (max-width:42rem){.sticky{display:flex}.nav{display:none}.top .btn{display:none}}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}.btn,.grid .card{transition:none}.grid .card:hover{transform:none}}
"""

# Each template has its own hero and rhythm. The page structure differs too (render.py builds different sections in a different order); this is the layout that goes with it.
TEMPLATE = {
    "clinic": """
.hero{padding:clamp(2.5rem,7vw,5rem) 0}
.hero .wrap{display:grid;gap:2.5rem;grid-template-columns:1fr}
@media (min-width:56rem){.hero .wrap{grid-template-columns:1.35fr 1fr;align-items:start}}
.appt{border:2px solid var(--ink);padding:1.5rem}
.appt h2{font-size:1.25rem;margin-bottom:1rem}
.appt table.hrs{font-size:.92rem}
.appt .btn{width:100%;margin-top:1rem}
.hero img.hi{margin-top:2rem;aspect-ratio:16/9;object-fit:cover;width:100%}
.svc .card{border-top-color:var(--a)}
""",
    "salon": """
.hero{padding:0}
.hero img.hi{width:100%;aspect-ratio:21/9;object-fit:cover;min-height:14rem}
.hero .wrap{padding-top:2rem;padding-bottom:3rem;display:grid;gap:1rem}
.hero h1{font-size:clamp(2.8rem,9vw,6rem)}
.menu2{columns:1;column-gap:3rem}
@media (min-width:52rem){.menu2{columns:2}}
.menu2 .grp{break-inside:avoid;margin-bottom:2rem}
.menu2 h3{border-bottom:2px solid var(--ink);padding-bottom:.5rem;margin-bottom:.25rem}
.gal{grid-template-columns:repeat(auto-fill,minmax(11rem,1fr))}
.gal img{aspect-ratio:3/4}
""",
    "restaurant": """
.hero{padding:clamp(2rem,6vw,4rem) 0}
.hero .wrap{display:grid;gap:2rem}
@media (min-width:56rem){.hero .wrap{grid-template-columns:1fr 1.1fr;align-items:end}}
.hero h1{font-size:clamp(3rem,10vw,6.5rem);text-transform:uppercase;letter-spacing:-.03em}
.hero img.hi{width:100%;aspect-ratio:4/5;object-fit:cover}
.mcat{margin-bottom:2.5rem}
.mcat h3{font-size:1.5rem;border-bottom:2px solid var(--ink);padding-bottom:.5rem;margin-bottom:.5rem}
.mcat .rows li{align-items:baseline}
.gal{grid-template-columns:repeat(auto-fill,minmax(16rem,1fr))}
""",
    "retail": """
.hero{padding:clamp(2.5rem,7vw,5rem) 0 0}
.hero .wrap{display:grid;gap:2rem}
@media (min-width:56rem){.hero .wrap{grid-template-columns:1fr 1fr;align-items:center}}
.hero img.hi{width:100%;aspect-ratio:1/1;object-fit:cover}
.info{display:grid;gap:0;grid-template-columns:repeat(auto-fit,minmax(14rem,1fr));margin-top:3rem;border-top:2px solid var(--ink)}
.info div{padding:1.25rem 1.25rem 1.25rem 0;border-bottom:1px solid var(--rule)}
.info strong{display:block;font-size:.78rem;letter-spacing:.12em;text-transform:uppercase;color:var(--mute);margin-bottom:.3rem}
.grid .card{border-top:0;border:1px solid var(--rule);padding:1rem}
""",
    "home_services": """
.hero{padding:clamp(2.5rem,7vw,5rem) 0;background:var(--soft)}
.hero .wrap{display:grid;gap:2rem}
@media (min-width:56rem){.hero .wrap{grid-template-columns:1.3fr 1fr;align-items:center}}
.hero .btn{min-height:3.5rem;font-size:1.1rem}
.hero img.hi{width:100%;aspect-ratio:4/3;object-fit:cover}
.hero .chips{margin-top:1.5rem}
.areas{columns:2 10rem;column-gap:2rem;list-style:none;margin:0;padding:0}
.areas li{padding:.35rem 0;border-bottom:1px solid var(--rule);break-inside:avoid}
""",
    "professional": """
.hero{padding:clamp(3rem,9vw,7rem) 0 clamp(2rem,5vw,3rem)}
.hero h1{font-size:clamp(2.6rem,8vw,5.5rem);max-width:16ch}
.hero .rule{border:0;border-top:2px solid var(--ink);margin:2.5rem 0 0}
.hero img.hi{margin-top:2rem;width:100%;aspect-ratio:21/9;object-fit:cover}
.pr{list-style:none;margin:0;padding:0;display:grid;gap:0}
.pr li{display:grid;gap:.5rem;padding:1.5rem 0;border-top:1px solid var(--rule)}
@media (min-width:52rem){.pr li{grid-template-columns:1fr 2fr;gap:2rem}}
.pr li:last-child{border-bottom:1px solid var(--rule)}
""",
}


def stylesheet(template_key: str) -> str:
    return (BASE + TEMPLATE[template_key]).strip() + "\n"
