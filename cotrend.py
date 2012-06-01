"""
Erik's cotrending functions.
"""
from scipy import ndimage as nd
from scipy import stats

import glob
import atpy

import tfind
import detrend
import keplerio
import scipy.cluster as cluster
from scipy import optimize
import ebls
import prepro

from numpy import ma
import numpy as np

def dtbvfitm(t,fm,bv):
    """
    Detrended Basis Vector Fit
    
    Parameters
    ----------
    t   : time 
    fm  : flux for a particular segment
    bv  : vstack of basis vectors

    Returns
    -------
    fdt  : Detrended Flux
    fcbv : Fit to the detrended flux

    """
    ncbv  = bv.shape[0]
    
    tm = ma.masked_array(t,copy=True,mask=fm.mask)
    mask  = fm.mask 

    bv = ma.masked_array(bv)
    bv.mask = np.tile(mask, (ncbv,1) )

    # Detrend the basis vectors
    bvtnd = [detrend.spldtm(tm,bv[i,:]) for i in range(bv.shape[0]) ] 
    bvtnd = np.vstack(bvtnd)
    bvdt  = bv-bvtnd

    # Detrend the flux
    ftnd  = detrend.spldtm(tm,fm)
    fdt   = fm-ftnd

    p1,fcbv = bvfitm(fdt,bvdt)

    return fdt,fcbv

def bvfitm(fm,bv):
    """
    Basis Vector Fit, masked

    Parameters
    ----------

    fm   : photometry masked
    bv   : basis vectors, stacked row-wise

    Returns
    -------
    fcbv : fit using a the CBVs

    """
    if type(fm) != np.ma.core.MaskedArray:
        fm = masked_array(fm)
        fm.mask = np.ones(fm.size).astype(bool)

    assert fm.size == bv.shape[1],"fm and bv must have equal length"
    mask  = fm.mask 

    p1          = np.linalg.lstsq( bv[:,~mask].T , fm[~mask] )[0]
    fcbv        = fm.copy()
    fcbv[~mask] = np.dot( p1 , bv[:,~mask] )
    return p1,fcbv

#
# Non-standard use functions below.
#











tq = 89.826658388163196
def cutQuarterPeriod(PG):
    """
    Remove multiples of the quarter spacing.
    """
    for i in range(12):
        PG = ma.masked_inside(PG,i*tq-1,i*tq+1)
    for i in range(24):
        PG = ma.masked_inside(PG,i*tq/2-1,i*tq/2+1)
    for i in range(36):
        PG = ma.masked_inside(PG,i*tq/3-1,i*tq/3+1)
    for i in range(48):
        PG = ma.masked_inside(PG,i*tq/4-1,i*tq/4+1)
    return PG

def peaks(mtd,twd):
    mf = nd.maximum_filter(mtd,twd)
    pks = np.unique(mf)
    cnt = np.array([mf[mf==p].size for p in pks])
    pks = pks[cnt==twd]
    return pks

def diag(mtd,twd):
    pks = peaks(mtd,twd)
    pks = sort(pks)

    mad = ma.median(ma.abs(mtd))
    max3day = mean(nd.maximum_filter(mtd,150))

    val   = (pks[-1],mean(pks[-3:]),mean(pks[-10:]),mad  ,max3day)
    dtype = [('maxpk',float),('pk3',float),('pk10',float),('mad',float),('max3day',float)]
    rd = np.array(val,dtype=dtype)

    return rd

def medfit(fdt,vec):
    vec = ma.masked_invalid(vec)
    fdt.mask = vec.mask = fdt.mask | vec.mask
    
    p0 = [0]
    def cost(p):
        return ma.median(ma.abs(fdt-p[0]*vec))
    p1 = optimize.fmin(cost,p0,disp=0)
    fit = ma.masked_array(p1[0] * vec,mask=fdt.mask)
    return fit






def coTrend(t,alg):
    kw = t.keywords

    if alg is 'RawCBV':
        fm = ma.masked_invalid(t.f)
    else:
        fm = ma.masked_array(t.f,mask=t.fmask)

    bg = ~fm.mask # shorthand for the good indecies

    cbv = [1,2,3,4,5,6]   
    q = kw['QUARTER']
    mod,out = keplerio.idQ2mo(kw['KEPLERID'],q)
    tBV = prepro.bvload(q,mod,out)

    bv  = np.vstack( [tBV['VECTOR_%i' % i] for i in cbv] )
    tDtCBV   = prepro.tcbvdt(t,'f','ef',q)
    fdt      = ma.masked_array(tDtCBV.fdt,mask=fm.mask)
    
    if (alg is 'RawCBV') or (alg is 'ClipCBV') :
        p1 = np.linalg.lstsq( bv[:,bg].T , fm[bg] )[0]
        tnd     = fm.copy()
        tnd[bg] = np.dot( p1 , bv[:,bg] )
        data,tnd = fm,tnd
    elif alg is 'DtSpl':
        data,tnd = fm,fm-fdt
    elif alg is 'DtCBV':
        tndDtCBV = ma.masked_array(tDtCBV.fcbv,mask=fm.mask)
        data,tnd = fdt,tndDtCBV
    elif alg is 'DtMed':
        vec = np.load('mom_cycle_q%i.npy' % kw['QUARTER'])
        tndMedCT = medfit(fdt,vec)
        data,tnd  = fdt,tndMedCT
    else:
        raise IOError('alg is not correct type')

    return data,tnd


twd = 20
from matplotlib import gridspec
from mpl_toolkits.axes_grid.anchored_artists import AnchoredText

tprop = dict(size=10,name='monospace')

def compCoTrend(tlc):
    fig = figure(figsize=(18,12))

    algL = ['RawCBV','ClipCBV']
    nalg = len(algL)
    gs = GridSpec(nalg+1,1)

    mtdL = []
    for i in range(nalg):
        alg = algL[i]
        time = tlc.time
        data = ma.masked_array(tlc[alg+'data'],mask=tlc[alg+'datamask'])
        tnd = ma.masked_array(tlc[alg+'tnd'],mask=tlc[alg+'tndmask'])

        pltDiagCoTrend(time,data,tnd,gs=gs[i]) 
        at = AnchoredText(alg,prop=tprop, frameon=True,loc=2)
        gca().add_artist(at)
        
    rcParams['axes.color_cycle'] = ['k','r','c','g']

    axmtd = plt.subplot(gs[-1],sharex=gca())
#    for mtd in mtdL:
#        axmtd.plot(t.TIME,mtd)
#
#    for mtd in mtdL:
#        mf = nd.maximum_filter(mtd,twd)
#        axmtd.plot(t.TIME,mf+50e-6)

#    rdL = [diag(mtd,twd) for mtd in mtdL]
#    rdL = hstack(rdL)
#    for n in rdL.dtype.names:
#        rdL[n] *= 1e6 

#    rdL = mlab.rec_append_fields(rdL,'alg',algL)
#    at = AnchoredText(mlab.rec2txt(rdL,precision=0),prop=tprop, frameon=True,loc=3)

#    axmtd.add_artist(at)
    axL = fig.get_axes()
    for ax in axL:
        ax.xaxis.set_visible(False)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5,prune='both'))
        ax.set_xlim(axL[0].get_xlim())
    ax.xaxis.set_visible(True)

    draw()
    fig.tight_layout()
    fig.subplots_adjust(hspace=0.001)
    draw()

def pltDiagCoTrend(time,data,fit,gs=None):
    res = data-fit

    if gs is None:
        smgs = GridSpec(4,1)
    else:
        smgs = gridspec.GridSpecFromSubplotSpec(4,1,subplot_spec=gs)

    axres = plt.subplot(smgs[0])
    axres.plot(time,res)

    plt.subplot(smgs[1:],sharex=axres)
    axfit.plot(time,data)
    axfit.plot(time,fit)

def compwrap(tset):
    tset = map(keplerio.ppQ,tset)

    for t in tset:
        compCoTrend(t)
        fig = gcf()
        fig.savefig('%09d.png' % t.keywords['KEPLERID'])


    
    if (alg is 'RawCBV') or (alg is 'ClipCBV') :
        p1 = np.linalg.lstsq( bv[:,bg].T , fm[bg] )[0]
        tnd     = fm.copy()
        tnd[bg] = np.dot( p1 , bv[:,bg] )
        data,tnd = fm,tnd
    elif alg is 'DtSpl':
        data,tnd = fm,fm-fdt
    elif alg is 'DtCBV':
        tndDtCBV = ma.masked_array(tDtCBV.fcbv,mask=fm.mask)
        data,tnd = fdt,tndDtCBV
    elif alg is 'DtMed':
        vec = numpy.load('mom_cycle_q%i.npy' % kw['QUARTER'])
        tndMedCT = medfit(fdt,vec)
        data,tnd  = fdt,tndMedCT



def compDTdata(t):
    """
    Emit the tables used to compare different detrending algorithns.
    """
    tgrid = atpy.Table(masked=True) # Store the different grid search results.
    tlc   = atpy.Table(masked=True) # Store the differnt detrending schemes
    
    tgrid.table_name = 'tgrid'
    tlc.table_name = 'tlc'
    
    fm = ma.masked_array(t.f,mask=t.fmask)

    for alg in ['RawCBV','ClipCBV','DtSpl','DtCBV','DtMed']:
        data,tnd = coTrend(t,alg)
        res = data - tnd
        dM = tfind.mtd(t.TIME,res.data,t.isStep,res.mask,20)

        for name,marr in zip(['data','tnd','dM'],[data,tnd,dM]):
            tlc.add_column(alg+name,marr.data)
            tlc.add_column(alg+name+'mask',marr.mask)
        
        PG,fom = repQper(t,dM,nQ=12)
        tgrid.add_column(alg+'fom',fom)

        
    PG = cutQuarterPeriod(PG)
    tgrid.add_column('PG',PG.data)
    tgrid.add_column('PGmask',PG.mask)
    
    tlc.add_column('time',t.TIME)
        
    tgrid.keywords = t.keywords
    tlc.keywords = t.keywords
    return tgrid,tlc

def repQper(t,dM,nQ=12):
    """
    Extend the quarter and compute the MES 
    """
    
    dM = [dM for i in range(nQ)]
    dM = ma.hstack(dM)

    PG0 = ebls.grid( nQ*90 , 0.5, Pmin=180)
    PcadG,PG = tfind.P2Pcad(PG0)

    res = tfind.pep(t.TIME[0],dM,PcadG)
    return PG,res['fom']


def corr(f1,f2):
    bgood = ~f1.mask & ~f2.mask
    return stats.pearsonr(f1[bgood],f2[bgood])[0]

def mcorr(fdtL):
    nlc = len(fdtL)
    corrmat = zeros((nlc,nlc))

    for i in range(nlc):
        for j in range(nlc):
            corrmat[i,j] = corr(fdtL[i],fdtL[j])

    return corrmat

def reorder(X):
    Z = cluster.hierarchy.linkage(X)
    dend = cluster.hierarchy.dendrogram(Z,no_plot=True)
    ind = array(dend['leaves'])
    return ind

def indord(ind):
    n = len(ind)
    x,y = mgrid[0:n,0:n]
    xs = x[ind]
    return xs


def corrplot(cms,t,fdts,binsize=20):
    """
    Make a correlation plot showing how correlated lightcurves are 
    """
    clf()
    fig = gcf()
    nbins = int(fdts.shape[0] / binsize)
    gs = plt.GridSpec(nbins,3)


    axim = fig.add_subplot(gs[:,0])
    axim.imshow(cms,vmin=0.1,vmax=0.5,aspect='auto',interpolation='nearest')
    axim.set_xlabel("star number")
    axim.set_ylabel("star number")

    for i in range(nbins):
        ax = fig.add_subplot(gs[i,1:3])
        start = i*binsize
        fdtb = [ fdts[i]/ median(fdts[i])  for i in range(start,start+10)]
        fdtb = ma.vstack(fdtb)
        med = ma.median(fdtb,axis=0)
        ax.plot(t,fdtb.T,',')
        ax.plot(t,med,lw=2,color='red')
        ax.xaxis.set_visible(False)
        ax.yaxis.set_visible(False)
        ylim(-15,15)

    ax.xaxis.set_visible(True)
    tight_layout()
    fig.subplots_adjust(hspace=0.001)
    
def dblock(X,dmi,dma):
    """
    Return block matrix off the diagonal.
    """
    n = X.shape[0]
    nn = dma-dmi
    x,y = mgrid[0:n,0:n]
    return X[(x>=dmi) & (x<dma) & (y>=dmi) & (y<dma)].reshape(nn,nn)

def peaks(mtd,twd):
    mf = nd.maximum_filter(mtd,twd)
    pks = np.unique(mf)
    cnt = np.array([mf[mf==p].size for p in pks])
    pks = pks[cnt==twd]
    return pks

def diag(mtd,twd):
    pks = peaks(mtd,twd)
    pks = sort(pks)

    mad = ma.median(ma.abs(mtd))
    max3day = mean(nd.maximum_filter(mtd,150))

    val   = (pks[-1],mean(pks[-3:]),mean(pks[-10:]),mad  ,max3day)
    dtype = [('maxpk',float),('pk3',float),('pk10',float),('mad',float),('max3day',float)]
    rd = np.array(val,dtype=dtype)

    return rd

def medfit(fdt,vec):
    vec = ma.masked_invalid(vec)
    fdt.mask = vec.mask = fdt.mask | vec.mask
    
    p0 = [0]
    def cost(p):
        return ma.median(ma.abs(fdt-p[0]*vec))
    p1 = optimize.fmin(cost,p0,disp=0)
    fit = ma.masked_array(p1[0] * vec,mask=fdt.mask)
    return fit