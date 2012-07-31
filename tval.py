"""
Transit Validation

After the brute force period search yeilds candidate periods,
functions in this module will check for transit-like signature.
"""
import numpy as np
from numpy import ma
from scipy import optimize
from scipy import ndimage as nd
import qalg

import copy
import keptoy
import tfind
from numpy.polynomial import Legendre
from matplotlib import mlab

import config

def val(t,fm,tres):
    """
    Validate promising transits.

    Wrapper function which does the following for a list of transit
    specified via `tres`:
    - Fits the transit with Protopapas (2005) `keptoy.P05` model.
    - For transits with S/N > hs2n look for harmonics.

    Parameters
    ----------
    t    : time
    fm   : masked flux array.
    tres : a record array with the parameters of the putative transit.
           - s2n. val evaluates transits with the highest S/N.
           - P
           - epoch
           - tdur
           - df
           
    Returns
    -------
    rval : a record array with following fields:
           - P     <- From best fit
           - epoch
           - tdur
           - df
           - s2n
    """


    trespks = tres[ nd.maximum_filter(tres['s2n'],3) == tres['s2n']  ]
    lcFitThresh = np.sort( trespks['s2n'] )[-nCheck]
    trespks = trespks[ trespks['s2n'] >  lcFitThresh ]

    def fcand(r):
        d = qalg.rec2d(r)
        resd = fitcand(t,fm,d)
        return qalg.d2rec(resd)

    tresfit = map(fcand,trespks)
    tresfit = np.hstack(tresfit)
    tresfit = tresfit[ tresfit['stbl'] ]   # Cut out crazy fits.

    def fharm(r):
        d = qalg.rec2d(r)
        resd = harmW(t,fm,d)
        return qalg.d2rec(resd)
    
    tresharm = map(fharm,tresfit[ tresfit['s2n'] > hs2n] )
    tresharm = np.hstack(tresharm)

    return tresfit,tresharm

def gridPk(rg,width=1000):
    """
    Grid Peak
    
    Find the peaks in the MES periodogram.

    Parameters
    ----------
    rg    : record array corresponding to the grid output.

    width : Width of the maximum filter used to compute the peaks.
            The peaks must be the highest point in width Pcad.  Pcad
            is not a uniformly sampled grid so actuall peak width (in
            units of days) will vary.

    Returns
    -------
    rgpk : A trimmed copy of rg corresponding to peaks.  We sort on
           the `s2n` key

    TODO
    ----
    Make the peak width constant in terms of days.

    """
    
    s2nmax = nd.maximum_filter(rg['s2n'],width)

    # np.unique returns the (sorted) unique values of the maximum filter.  
    # rid give the indecies of us2nmax to reconstruct s2nmax
    # np.allclose(us2nmax[rid],s2nmax) evaluates to True

    us2nmax,rid = np.unique(s2nmax,return_inverse=True)
    
    bins = np.arange(0,rid.max()+2)
    count,bins = np.histogram(rid,bins )
    pks2n = us2nmax[ bins[count>=width] ]
    pks2n = np.rec.fromarrays([pks2n],names='s2n')
    rgpk  = mlab.rec_join('s2n',rg,pks2n)
    return rgpk

def getT(time,P,epoch,wd):
    """
    Get Transits

    time : Time series
    P    : Period
    epoch: epoch
    wd   : How much data to return for each slice.

    Returns
    -------
    Time series phase folded with everything but regions of width `wd`
    centered around epoch + (0,1,2,...)*P

    Note
    ----

    plot(tfold,fm) will not plot all the transit for some reason.
    Instead, do plot(tfold[~tfold.mask],fm[~tfold.mask])

    """
    tfold = time - epoch + P /2 #  shift transit to (0.5, 1.5, 2.5) * P
    tfold = np.mod(tfold,P)     #  Now transits are at 0.5*P
    tfold -= P/2
    tfold = ma.masked_outside(tfold,-wd/2,wd/2)
    tfold = ma.masked_invalid(tfold)
    return tfold

def t0shft(t,P,t0):
    """
    Epoch shift

    Find the constant shift in the timeseries such that t0 = 0.

    Parameters
    ----------
    t  : time series
    P  : Period of transit
    t0 : Epoch of one transit (does not need to be the first).

    Returns
    -------
    dt : Amount to shift by.
    """
    t  = t.copy()
    dt = 0

    t  -= t0 # Shifts the timeseries s.t. transits are at 0,P,2P ...
    dt -= t0

    # The first transit is at t =  nFirstTransit * P
    nFirstTrans = np.ceil(t[0]/P) 
    dt -= nFirstTrans*P 

    return dt

def transLabel(t,P,t0,tdur,cfrac=1,cpad=0):
    """
    Transit Label

    Mark cadences as:
    - transit   : in transit
    - continuum : just outside of transit (used for fitting)
    - other     : all other data

    Parameters
    ----------
    t     : time series
    P     : Period of transit
    t0    : epoch of one transit
    tdur  : transit duration
    cfrac : continuum defined as points between tdur * (0.5 + cpad)
            and tdur * (0.5 + cpad + cfrac) of transit midpoint cpad

    Returns
    -------
    tLbl  : numerical labels for transit region starting at 0
    cLbl  : numerical labels for continuum region starting at 0
    """

    t = t.copy()
    t += t0shft(t,P,t0)
    print t[0]
    tLbl = np.zeros(t.size,dtype=int) - 1
    cLbl = np.zeros(t.size,dtype=int) - 1 
    
    iTrans   = 0 # number of transit, starting at 0.
    tmdTrans = 0 # time of iTrans mid transit time.  
    while tmdTrans < t[-1]:
        # Time since mid transit in units of tdur
        t0dt = np.abs(t - tmdTrans) / tdur 
        bt = t0dt < 0.5
        bc = (t0dt > 0.5 + cpad) & (t0dt < 0.5 + cpad + cfrac)
        
        tLbl[bt] = iTrans
        cLbl[bc] = iTrans

        iTrans += 1 
        tmdTrans = iTrans * P

    return tLbl,cLbl

def LDT(t,fm,cLbl,tLbl):
    """
    Local Detrending

    A simple function that subtracts a polynomial trend from the
    lightcurve excluding a region around the transit.

    Parameters
    ----------
    t    : time
    f    : masked flux array
    cLbl : Labels for continuum regions

    
    Returns
    -------
    fldt : local detrended flux
    """

    fldt    = ma.masked_array( np.zeros(t.size) , True ) 
    
    for i in range(cLbl.max() + 1):
        bc = (cLbl == i )
        fc = fm[bc]
        tc = t[bc]
        bldt = ( tLbl == i ) | (cLbl == i) 
        tldt = t[bldt]

        if fc.count() > 4:
            shft = - np.mean(tc)
            tc   -= shft 
            tldt -= shft
            pfit = np.polyfit(tc,fc,1)
            fldt[bldt] = fm[bldt] - np.polyval(pfit,tldt)
            fldt.mask[bldt] = fm.mask[bldt]

    return fldt


def trsh(P,tbase):
    ftdurmi = 0.5
    tdur = keptoy.a2tdur( keptoy.P2a(P) ) 
    tdurmi = ftdurmi*tdur 
    dP     = tdurmi * P / tbase
    depoch = tdurmi

    return dict(dP=dP,depoch=depoch)
    
def objMT(p,time,fdt):
    """
    Multitransit Objective Function
    """
    fmod = keptoy.P05(p,time)
    resid = (fmod - fdt)/1e-4
    obj = (resid**2).sum() 
    return obj

def obj1T(p,t,f):
    """
    Single Transit Objective Function
    """
    model = keptoy.P051T(p,t)
    resid  = (model - f)/1e-4
    obj = (resid**2).sum()
    return obj


def id1T(t,fm,p,wd=2.,usemask=True):
    """
    Grab the indecies and midpoint of a putative transit. 
    """
    tdur  = p['tdur']

    tdurcad  = round(tdur/keptoy.lc)
    wdcad    = round(wd/keptoy.lc)

    mask = fm.mask | ~tfind.isfilled(t,fm,tdurcad)

    ### Determine the indecies of the points to fit. ###
    # Exclude regions where the convolution returned a nan.
    ms   = midTransId(t,p)
    if usemask:
        ms   = [m for m in ms if ~mask[m] ]

    sLDT = [ getSlice(m,wdcad) for m in ms ]
    x = np.arange(fm.size)
    idL  = [ x[s][~fm[s].mask] for s in sLDT ]
    idL  = [ id for id in idL if id.size > 10 ]

    return ms,idL

def fitcand(t,fm,p,full=False):
    """
    Perform a non-linear fit to a putative transit.

    Parameters
    ----------
    t  : time
    fm : flux
    p  : trial parameter (dictionary)
    full : Retrun tdt and fdt

    Returns
    -------
    res : Dictionary with the following parameters.
          - P
          - epoch
          - df
          - tdur
          - s2n
          - stbl    = boolean variable if fit is well behaved.
          - tdt  - time
          - fdt  - detrended flux


    Todo
    ----

    Add priors in for P.  tdur goes negative, but the sign doesn't matter
    """
    dtL  = LDTwrap(t,fm,p)
    dt   = np.hstack(dtL)

    fdt = dt['fdt']
    tdt = dt['tdt']

    p0  = np.array([p['P'],p['epoch'],p['df'],p['tdur']])
    p1  = optimize.fmin_powell(objMT,p0,args=(tdt,fdt),disp=False)

    # Hack to prevent negative transit duration.
    p1[3] = np.abs(p1[3])

    dp = (p0[:2]-p1[:2])
    if (abs(dp) > np.array([dP,depoch])).any():
        stbl = False
    elif p1[0] < 0:
        stbl = False
    else:
        stbl = True

    tfold = getT(tdt,p['P'],p['epoch'],p['tdur'])
    fdt   = ma.masked_array(fdt,mask=tfold.mask)
    tdt   = ma.masked_array(tdt,mask=tfold.mask)

    s2n = s2n_fit(fdt,tdt,p1)
    res = dict(P=p1[0],epoch=p1[1],df=p1[2],tdur=p1[3],s2n=s2n,stbl=stbl)

    if full:
        res['fdt'] = fdt
        res['tdt'] = tdt

    return res

def s2n_mean(fdt):
    return -ma.mean(fdt)/ma.std(fdt)*np.sqrt(fdt.count())

def s2n_med(fdt):
    sig = ma.median(fdt)
    noise = ma.median(abs(fdt-sig))
    return -sig/noise*np.sqrt(fdt.count())

def s2n_fit(fdt,tdt,p):
    """
    Evaluate S/N taking the best fit depth as signal and the scatter
    about the residuals as the noise.
    """
    model = keptoy.P05(p,tdt)
    sig   = p[2]
    resid = fdt-model
    noise = ma.median(abs(resid))
    s2n = sig/noise*np.sqrt(fdt.count() )
    return s2n

thresh = 0.001

def window(fl,PcadG):
    """
    Compute the window function.

    The fraction of epochs that pass our criteria for transit.
    """

    winL = []
    for Pcad in PcadG:
        flW = tfind.XWrap(fl,Pcad,fill_value=False)
        win = (flW.sum(axis=0) >= 3).astype(float)
        npass = np.where(win)[0].size
        win =  float(npass) / win.size
        winL.append(win)

    return winL

def midTransId(t,p):
    """
    Mid Transit Index

    Return the indecies of mid transit for input parameters.

    Parameters
    ----------

    t - timeseries
    p - dictionary with 'P','epoch','tdur'

    """
    P     = p['P']
    epoch = p['epoch']

    epoch = np.mod(epoch,P)
    tfold = np.mod(t,P)
    
    ms = np.where(np.abs(tfold-epoch) < 0.5 * keptoy.lc)[0]
    ms = list(ms)
    return ms


def harmSearch(res,t,fm,Pcad0,ver=False):
    """
    Harmonic Search

    Look for harmonics of P by computing MES at 1/4, 1/3, 1/2, 2, 3, 4.

    Parameters
    ----------
    
    res   : result from the grid searh
    t     : time
    fm    : flux
    Pcad0 : initial period in
    
    Returns
    -------

    rLarr : Same format as grid output.  If the code conveged on the
            correct harmonic, the true peak will be in here.
    """

    harmL = np.hstack([1,config.harmL])

    imax = 4    
    i = 0 # iteration counter
    bfund = False # Is Pcad0 the fundemental?

    while (bfund is False) and (i < imax):
        def harmres(h):
            Ph = Pcad0 * h
            pkwd = Ph / t.size # proxy for peak width
            pkwdThresh = 0.03
            if pkwd > pkwdThresh:
                dP = np.ceil(pkwd / pkwdThresh)
            else: 
                dP = 1

            P1 = np.floor(Ph) - dP
            P2 = np.ceil(Ph)  + dP

            isStep = np.zeros(fm.size).astype(bool)
            twdG = [3,5,7,10,14,18]
            rtd = tfind.tdpep(t,fm,isStep,P1,P2,twdG)
            r   = tfind.tdmarg(rtd)
            return r

        rL = map(harmres,harmL)
        hs2n = [np.nanmax(r['s2n']) for r in rL]
        rLarr = np.hstack(rL)
        
        hs2n = ma.masked_invalid(hs2n)
        hs2n.fill_value=0
        hs2n = hs2n.filled()

        if ver is True:
            np.set_printoptions(precision=1)
            print harmL*Pcad0*keptoy.lc
            print hs2n

        if np.argmax(hs2n) == 0:
            bfund =True
        else:
            jmax = np.nanargmax(rLarr['s2n'])
            Pcad0 = rLarr['Pcad'][jmax]

        i+=1

    return rLarr

def pd2a(d):
    return np.array([d['P'],d['epoch'],d['df'],d['tdur']])

def pa2d(a):
    return dict(P=a[0],epoch=a[1],df=a[2],tdur=a[3])

def getSlice(m,wdcad):
    """
    Get slice
    
    Parameters
    ----------
    m    : middle index (center of the slice).
    wdcad : width of slice list (units of cadence).

    """

    return slice( m-wdcad/2 , m+wdcad/2 )

def tdict(d,prefix=''):
    """
    
    """
    outcol = ['P','epoch','df','tdur']

    incol = [prefix+oc for oc in outcol]

    outd = {}
    for o,c in zip(outcol,incol):
        try:
            outd[o] = d[c]
        except KeyError:
            pass

    return outd

def nT(t,mask,p):
    """
    Simple helper function.  Given the transit ephemeris, how many
    transit do I expect in my data?
    """
    
    trng = np.floor( 
        np.array([p['epoch'] - t[0],
                  t[-1] - p['epoch']]
                 ) / p['P']).astype(int)

    nt = np.arange(trng[0],trng[1]+1)
    tbool = np.zeros(nt.size).astype(bool)
    for i in range(nt.size):
        it = nt[i]
        tt = p['epoch'] + it*p['P']
        # Find closest time.
        dt = abs(t - tt)
        imin = np.argmin(dt)
        if (dt[imin] < 0.3) & ~mask[imin]:
            tbool[i] = True

    return tbool
