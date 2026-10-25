import numpy as np
from scipy.optimize import minimize_scalar
def prof(p,q):
    e1=np.exp((2-p)/.25);e2=np.exp((2-q)/.25);return (p-1)*e1/(e1+e2+1)
_c={}
def BR(q):
    q=round(q,6)
    if q not in _c: _c[q]=minimize_scalar(lambda p:-prof(p,q),bounds=(1,3),method='bounded').x
    return _c[q]
p0=1.90; H=15; K=10
def run(rho,delta,cut,a_mode):
    m=p0-BR(p0)
    out={}
    for br in ['sham','cut']:
        q=[p0]*(H+2); pB=[p0]*(H+2)
        if br=='cut': q[1]=BR(p0)   # period t index1
        for h in range(2,H+2):
            if a_mode=='persist' and br=='cut':
                q[h]=q[h-1]  # A stays low
            target=m+BR(q[h-1])
            if br=='cut' and delta>0 and h-1<=K: target-=delta
            pB[h]=rho*pB[h-1]+(1-rho)*target
        out[br]=(q,pB)
    (qs,ps),(qc,pc)=out['sham'],out['cut']
    dp=[pc[h]-ps[h] for h in range(2,H+2)]
    dbr=[BR(qc[h-1])-BR(qs[h-1]) for h in range(2,H+2)]
    M1=dp[0]-dbr[0]
    M2=sum(a-b for a,b in zip(dp,dbr))
    d=0;M3=0
    for a,b in zip(dp,dbr):
        d=rho*d+(1-rho)*b; M3+=a-d
    return M1,M2,M3
for a_mode in ['impulse','persist']:
    print('A',a_mode)
    for rho in [0,0.5,0.8,0.92]:
        for delta in [0,0.1]:
            M1,M2,M3=run(rho,delta,None,a_mode)
            print(f' rho={rho} delta={delta}: one-period {M1:+.3f}  static-sum {M2:+.3f}  dynamic {M3:+.3f}')

def run_hat(rho,rho_hat,delta,a_mode):
    m=p0-BR(p0); out={}
    for br in ['sham','cut']:
        q=[p0]*(H+2); pB=[p0]*(H+2)
        if br=='cut': q[1]=BR(p0)
        for h in range(2,H+2):
            if a_mode=='persist' and br=='cut': q[h]=q[h-1]
            target=m+BR(q[h-1])
            if br=='cut' and delta>0 and h-1<=K: target-=delta
            pB[h]=rho*pB[h-1]+(1-rho)*target
        out[br]=(q,pB)
    (qs,ps),(qc,pc)=out['sham'],out['cut']
    d=0;M3=0
    for h in range(2,H+2):
        b=BR(qc[h-1])-BR(qs[h-1]); d=rho_hat*d+(1-rho_hat)*b; M3+=(pc[h]-ps[h])-d
    return M3
print('misestimated rho, true 0.92, persist')
for rh in [0.8,0.87,0.92,0.97]:
    print(rh, 'innocent',round(run_hat(0.92,rh,0,'persist'),3),'punisher',round(run_hat(0.92,rh,0.1,'persist'),3))
